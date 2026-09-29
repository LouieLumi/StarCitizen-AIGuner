"""How does the view follow our turns? Estimated from a session run with --dither.

    python host/main.py --enable --dither 12 --seconds 180   # lock targets with T as usual
    python tools/turret_ident.py logs/session_....csv

While tracking, main.py adds random -N/0/+N counts to each frame's command. The
pip moves by the target's own motion minus our turning:

    pip[k] - pip[k-1] = target motion[k] - sum_L h[L] * sent[k-L]

Regressing on the sent counts alone is biased: the controller reacts to the
target, so sent counts and target motion are correlated. The dither isn't - it
is used as the instrument (instrumental variables), which leaves the target's
motion as plain noise. h[L] is the share of a count's turn that shows up L
frames later; its running sum is the step response. Works with moving targets;
needs a few thousand frames with a visible pip (2-3 minutes of tracking).
"""

from __future__ import annotations

import argparse
import csv
import sys

import numpy as np

MAX_LAG = 15
MAX_FRAME_GAP_S = 0.06  # dropped frames break the lag arithmetic
MAX_STEP_PX = 80  # bigger pip jumps are detection switches, not motion


def _f(v) -> float:
    return float(v) if v not in ("", None) else np.nan


def load(path: str) -> dict[str, np.ndarray]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "dither_x" not in rows[0]:
        raise SystemExit(f"{path}: no dither columns - run main.py with --dither")
    cols = ("timestamp", "target_x", "target_y", "pid_x", "pid_y", "dither_x", "dither_y")
    return {c: np.array([_f(r[c]) for r in rows]) for c in cols}


def design(d: dict[str, np.ndarray], axis: str):
    """y, X (lagged sent counts), Z (lagged dither) for one axis."""
    t, p = d["timestamp"], d[f"target_{axis}"]
    u, r = np.nan_to_num(d[f"pid_{axis}"]), np.nan_to_num(d[f"dither_{axis}"])
    gap = np.r_[np.inf, np.diff(t)] > MAX_FRAME_GAP_S  # gap[k]: frame k doesn't follow k-1
    Y, X, Z = [], [], []
    for k in range(MAX_LAG + 1, len(t)):
        if np.isnan(p[k]) or np.isnan(p[k - 1]) or gap[k - MAX_LAG:k + 1].any():
            continue
        dy = p[k] - p[k - 1]
        if abs(dy) > MAX_STEP_PX:
            continue
        lags = np.arange(1, MAX_LAG + 1)
        Y.append(dy)
        X.append(np.r_[u[k - lags], 1.0])
        Z.append(np.r_[r[k - lags], 1.0])
    return np.array(Y), np.array(X).reshape(-1, MAX_LAG + 1), np.array(Z).reshape(-1, MAX_LAG + 1)


def iv(Y, X, Z):
    """Instrumental-variables estimate and standard errors."""
    ZX = Z.T @ X
    b = np.linalg.solve(ZX, Z.T @ Y)
    e = Y - X @ b
    inv = np.linalg.inv(ZX)
    cov = e.var() * inv @ (Z.T @ Z) @ inv.T
    return b, np.sqrt(np.diag(cov))


def response(D: int, a: float) -> np.ndarray:
    """Share of a turn that shows up in each of the frames 1..MAX_LAG after sending."""
    L = np.arange(1, MAX_LAG + 1)
    s = np.where(L >= D, 1 - a ** np.maximum(L - D + 1, 1), 0.0)
    return np.diff(np.r_[0.0, s])


def fit_2sls(Y, X, Z) -> tuple[int, float, float]:
    """Delay D, smoothing a and gain G minimizing the 2SLS objective with the
    lag coefficients restricted to -G * response(D, a): only the part of the pip
    motion the dither explains is fitted, so the target's motion (and the
    controller's reaction to it) doesn't bias the result."""
    Q, _ = np.linalg.qr(Z)
    Yp = Q @ (Q.T @ Y)
    best = None
    for D in range(1, 8):
        for a in np.arange(0.0, 0.96, 0.05):
            x = X[:, :MAX_LAG] @ response(D, a)
            xp = Q @ (Q.T @ x)
            # intercept: projected on Z's constant column as well
            A = np.c_[xp, Q @ (Q.T @ X[:, -1])]
            coef, *_ = np.linalg.lstsq(A, Yp, rcond=None)
            J = float(np.sum((Yp - A @ coef) ** 2))
            if best is None or J < best[3]:
                best = (D, float(a), float(-coef[0]), J)
    return best[:3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--bootstrap", type=int, default=100, help="resamples for the uncertainty (0 = off)")
    args = ap.parse_args()

    parts = {"x": [], "y": []}
    for path in args.csv:
        d = load(path)
        n_dither = int(np.sum((d["dither_x"] != 0) & ~np.isnan(d["dither_x"])))
        print(f"{path}: {len(d['timestamp'])} frames, {n_dither} with dither")
        for axis in parts:
            parts[axis].append(design(d, axis))

    results = {}
    for axis in ("x", "y", "both"):
        chosen = [p for a in ("x", "y") for p in parts[a]] if axis == "both" else parts[axis]
        Y = np.concatenate([p[0] for p in chosen])
        X = np.concatenate([p[1] for p in chosen])
        Z = np.concatenate([p[2] for p in chosen])
        if len(Y) < 200 or not Z[:, :-1].any():
            print(f"{axis}: not enough samples ({len(Y)})")
            continue
        b, se = iv(Y, X, Z)
        h, h_se = -b[:MAX_LAG], se[:MAX_LAG]  # view shift per count (pip moves the other way)
        results[axis] = (len(Y), h, h_se)

    if not results:
        return 1
    print(f"\nview shift per count, L frames after sending (1 = next captured frame):")
    print("  L  " + "  ".join(f"{a:>17s}" for a in results) + "   step (both)")
    both = results.get("both")
    step = np.cumsum(both[1]) if both else None
    for L in range(MAX_LAG):
        cells = "  ".join(f"{h[L]:+.3f} +-{se[L]:.3f}" for _, h, se in results.values())
        tail = ""
        if step is not None:
            share = step[L] / step[-4:].mean()
            tail = f"   {step[L]:+.2f} {share:4.0%} " + "#" * int(round(max(0, min(1.2, share)) * 30))
        print(f" {L + 1:2d}  {cells}{tail}")
    print("samples: " + ", ".join(f"{a} {n}" for a, (n, _, _) in results.items()))
    if "both" not in results:
        return 0
    Y = np.concatenate([p[0] for a in ("x", "y") for p in parts[a]])
    X = np.concatenate([p[1] for a in ("x", "y") for p in parts[a]])
    Z = np.concatenate([p[2] for a in ("x", "y") for p in parts[a]])
    D, a, g = fit_2sls(Y, X, Z)
    # bootstrap over blocks of consecutive samples (target motion is correlated in time)
    rng = np.random.default_rng(0)
    block = 30
    starts = np.arange(0, len(Y) - block, block)
    boots = []
    for _ in range(args.bootstrap):
        idx = np.concatenate([np.arange(s0, s0 + block) for s0 in rng.choice(starts, len(starts))])
        boots.append(fit_2sls(Y[idx], X[idx], Z[idx]))
    tau = -1 / np.log(a) if a > 0 else 0.0
    print(f"\nmodel (restricted 2SLS): nothing for {D - 1} frame(s), then the view closes the rest by a "
          f"share of {1 - a:.2f} per frame (time constant {tau:.1f} frames), total {g:.2f} px/count")
    if boots:
        bD, ba, bg = (np.array(v) for v in zip(*boots))
        print(f"  bootstrap ({len(boots)}x): delay {np.percentile(bD, 10):.0f}-{np.percentile(bD, 90):.0f} "
              f"(D={D} in {100 * np.mean(bD == D):.0f}%), smoothing {np.percentile(ba, 10):.2f}-"
              f"{np.percentile(ba, 90):.2f}, gain {np.percentile(bg, 10):.2f}-{np.percentile(bg, 90):.2f} (10-90%)")
    print(f"config: control.view_delay_frames = {D}, control.view_smoothing = {a:.2f}, "
          f"control.px_per_count = {g:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# 一起改

有问题可以提 Issue，有改进也欢迎直接提 PR。如果是识别不准，尽量带上分辨率、炮塔、配置和一张出问题的画面；只有一句“没跟上”，我这边很难复现。截图里的聊天和个人信息记得先遮一下。

## 本地跑测试

我用 Python 3.12。Windows 环境按首页安装后，再装开发依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

macOS / Linux 也能跑离线测试和回放：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/controller_test.py
```

实时截屏和浮窗用到了 Windows API，要在 Windows 上跑。依赖文件只会在 Windows 下安装 DXCAM。

`tests/` 是不接硬件的测试，`tools/pico_test.py` 是会实际操作 Pico 的工具，pytest 不会收集它。

## 提交改动

PR 里说清楚改了什么、解决什么问题、怎么试过就行。涉及捕获或控制的改动，也请写一下是只跑了离线回放，还是已经接 Pico 在游戏里试过。

改了配置或启动方式的话，顺手把文档一起改掉。日志、录像、虚拟环境、SDK 和个人配置不用提交。需要用录像复现问题时，先截取能说明问题的一小段。

贡献的代码沿用仓库的 [PolyForm Noncommercial 1.0.0](LICENSE) 许可。引用第三方代码请保留原来的许可和归属。

# StarCitizen AIGuner

[English](README.en.md)

这是我给自己刷高塔打钱做的 Star Citizen 自动炮手，已经在游戏里跑通，也在正常使用。

它通过看屏幕上的 HUD 来找目标、跟踪提前量点，再让 Pico 模拟鼠标去转炮塔。进入射程后可以自动开火，丢失目标后继续寻找下一个。整个过程不读游戏内存，也不往游戏进程里注入东西。

我用的是 **Pico 2 W + Windows + Python**，目前的参数是在 **2560×1440、Polaris 炮塔、FPS 鼠标模式**下调的。换分辨率、炮塔或者鼠标灵敏度，需要跟着改配置。

## 免责声明

这是我自己刷高塔打钱用的工具，放出来是分享代码和实现思路。**CIG 不允许使用这类自动化工具，使用可能导致封号或其他账号处罚。**

是否使用请自己决定。因使用本项目导致的封号、账号损失或其他后果，由使用者自行承担，我不承担相关责任。

![游戏录制中的检测和跟踪效果](docs/assets/track_strip.png)

## 怎么实现的

游戏已经把提前量点画在屏幕上了，所以我直接识别这个点，让炮塔准星跟着它走。这里没有用大模型，也不需要 API Key，主要是 OpenCV 和控制算法。

Python 用 **DXCAM** 抓取游戏画面，**OpenCV** 按颜色和形状找出准星、提前量点、射程圈。白色和绿色的提前量点都能识别，绿色用来判断目标是否进入射程。找不到提前量点时，就根据红色目标标签或屏幕外箭头转过去；没有锁定目标时，会尝试按 T 锁定。

识别出来的位置会交给**卡尔曼滤波器**，估计目标的位置和速度。这样提前量点短暂被准星、激光或目标标记挡住时，不至于马上丢掉跟踪。

控制这部分用了 **PD 控制、速度前馈和 Smith 预估**。炮塔收到鼠标位移后，画面不会立刻跟着动，中间有延迟和平滑。如果只看当前误差一直修正，就容易转过头。所以我也记录自己发出去的鼠标指令，估计还有多少转向没体现在画面里，再算下一帧该怎么动。

最后通过 **pyserial** 把鼠标位移、按键和开火指令发给 Pico。Pico 上跑的是用 **C、Pico SDK 和 TinyUSB** 写的固件，在电脑上识别成 USB 串口和 HID 设备。主机和游戏在同一台电脑上，Pico 用 USB 接上就行，不用第二台电脑，也没用到 Wi-Fi。

```text
游戏画面 → DXCAM 截屏 → OpenCV 检测 → 跟踪和控制 → USB 串口 → Pico → 鼠标/键盘输入
```

更具体的处理过程写在[实现笔记](docs/architecture.md)里，HUD 的形状和颜色记录在[这里](docs/hud.md)。

## 安装

准备一块 **Pico 2 W** 和一根能传数据的 USB 线，电脑上装好 **Python 3.12** 和 **Git**。主程序在 Windows 上运行。

打开 PowerShell：

```powershell
git clone https://github.com/LouieLumi/StarCitizen-AIGuner.git
cd StarCitizen-AIGuner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

接着给 Pico 刷固件。编译需要 ARM 工具链、Pico SDK、CMake、Ninja 和 picotool，我把安装和刷写步骤单独放在了[固件说明](docs/firmware.md)里。

刷好后，电脑上应该能看到 `AI Crew Controller`，程序会自动找它的串口。

### 改配置

配置文件是 [`config/config.yaml`](config/config.yaml)。先检查这几项：

| 配置 | 要改什么 |
|---|---|
| `screen` | 屏幕分辨率，默认 2560×1440 |
| `capture` | 用哪张显卡、哪个显示器抓画面 |
| `roi` | 检测 HUD 的区域，默认从 `(680,270)` 开始，大小 `1200×900` |
| `aim` | 准星在 ROI 内的位置，检测不到准星时用作参考 |
| `control` | 炮塔灵敏度、响应延迟和控制参数 |
| `recording.dir` | 录像和事件截图的保存位置，默认 `recordings/` |

如果不是 2560×1440，还要调整 `finder` 里的排除区域、检测形状的尺寸和射程圈半径。这些参数目前都是像素值，不会随分辨率自动缩放。

想把自己的配置单独留一份，可以复制成 `config/config.local.yaml`，启动时加 `--config config/config.local.yaml`。这个文件不会被 Git 提交。

## 使用

进入炮塔后，先把游戏里的炮塔鼠标切到 **FPS 模式**。虚拟摇杆模式下，鼠标不动了炮塔也可能继续转，当前这套控制参数是按 FPS 模式调的。

日常使用直接双击 **`start_gunner.bat`**。它启动时会同时打开火控和自动开火：找目标、转过去、跟踪、进入射程后开火。

屏幕上有一个浮窗，两个开关分别控制：

- **火控系统**：自动锁定、寻找和跟踪目标，关掉后全部停止。
- **武器系统**：是否自动开火。可以只开火控，自己决定什么时候开枪。

浮窗可以拖动，点右上角的锁固定位置。切出游戏后，程序会暂停输入。退出直接关控制台，或者按 Ctrl+C。

**打开聊天框前记得关火控**，否则自动锁定用的 T 会打进聊天框。

如果想从命令行启动，在项目目录里运行：

```powershell
# 启动后两个开关都关着，在浮窗里手动打开
.venv\Scripts\python.exe host\main.py

# 启动就开启火控和自动开火，和双击 bat 一样
.venv\Scripts\python.exe host\main.py --enable --auto-fire

# 只跑识别和跟踪，不向 Pico 发指令；没有 Pico 也可以试
.venv\Scripts\python.exe host\main.py --dry-run --enable --seconds 30
```

这些命令要在 Windows 已登录的桌面里运行。如果是通过 SSH 启动，见[操作说明](docs/usage.md)里的 `desktop_run.ps1`。

自动开火会先等射程信号稳定，再开始射击。开始后默认一直连射，直到锁定目标丢失超过 1 秒；关掉任一开关会停止。这个等待时间可以在 `fire.stop_after_unlocked_s` 里改。

Pico 也做了超时处理：100 ms 收不到新命令就释放按键、停止鼠标移动、摇杆回中。

## 想继续改的话

主机代码在 `host/`，Pico 固件在 `firmware/`。`tools/` 里放了录制、回放、检测调试和炮塔标定工具，具体命令见[操作与调试](docs/usage.md)。

换炮塔或改灵敏度后，可以用 `tools/turret_ident.py` 重新算响应延迟、平滑和增益。录制回放不需要连接 Pico，适合拿同一段画面反复调检测参数。录像和日志默认放在 `recordings/`、`logs/`，不会上传到仓库。无损录像很占空间，录之前留意一下磁盘容量。

离线测试和开发环境见 [CONTRIBUTING.md](CONTRIBUTING.md)。有问题可以提 Issue，尽量带上分辨率、炮塔、配置和出问题的画面，方便复现。

## 许可

代码放出来给大家学习、使用和修改，**不要用于商业用途**。具体条款采用 [PolyForm Noncommercial 1.0.0](LICENSE)，分发时请保留许可证和[版权说明](NOTICE)。

这是我的个人项目，与 CIG / RSI 没有官方关系。文档中的 Star Citizen 游戏画面和商标归各自权利人所有。

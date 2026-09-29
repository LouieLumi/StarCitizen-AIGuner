# StarCitizen AIGuner

[English](README.en.md) · [实现原理](docs/architecture.md) · [固件说明](docs/firmware.md) · [操作与调试](docs/usage.md)

这是我为 Star Citizen 开发的外置自动炮手，主要用于自己刷高塔打钱。目前已经完成实机验证，并在日常使用。

程序通过屏幕画面识别炮塔 HUD，跟踪游戏给出的提前量点，再通过 Pico 输出 USB 鼠标和键盘指令，完成目标搜索、瞄准和自动开火。实现上使用计算机视觉和控制算法，不读取游戏内存，也不向游戏进程注入代码。

我使用的环境是 **Windows、Python 3.12、Pico 2 W**，配置针对 **2560×1440 分辨率、Polaris 炮塔和 FPS 鼠标模式**做过标定。更换分辨率、炮塔或鼠标灵敏度后，需要调整对应参数。

## 免责声明

**CIG 不允许使用这类自动化工具，使用本项目可能导致封号或其他账号处罚。**

公开源码仅用于分享实现方法，不代表获得 CIG 授权。请自行决定是否使用；因使用本项目造成的封号、账号损失及其他后果，由使用者自行承担，作者不承担相关责任。

![游戏录制中的检测和跟踪效果](docs/assets/track_strip.png)

## 实现原理

游戏 HUD 已经提供了提前量点，因此我直接使用这个点作为瞄准目标。程序不需要自行计算弹道，也不依赖模型权重或云端 API。

```text
游戏画面 → 屏幕捕获 → HUD 检测 → 目标跟踪与控制 → USB 串口 → Pico HID → 游戏输入
```

**画面识别。** DXCAM 捕获游戏画面，OpenCV 根据 HSV 颜色、连通域和形状特征识别准星、提前量点与射程圈。没有找到提前量点时，程序根据红色目标标签或屏幕外箭头转向；持续看不到锁定提示时，尝试按 T 锁定目标。

**目标跟踪。** 卡尔曼滤波器估计提前量点的位置和速度，过滤异常观测，并处理短暂遮挡。新轨迹需要连续多帧确认，已有轨迹则允许在预测位置附近使用部分遮挡的观测。

**炮塔控制。** PD 控制器将准星与提前量点的误差转换成鼠标位移，并加入速度前馈。炮塔响应存在延迟和平滑，单纯根据当前画面修正容易产生过冲。我在控制中加入了自身运动补偿和 Smith 预估，分别处理自身转向引起的画面位移，以及已经发送但尚未体现在画面中的控制量。

**输入输出。** Python 通过 pyserial 向 Pico 发送指令。固件使用 C、Pico SDK 和 TinyUSB，实现 USB CDC 串口、鼠标/键盘 HID，以及预留的 7 轴 32 键摇杆 HID。主程序与游戏运行在同一台电脑上，Pico 通过 USB 连接。

**射程与开火。** 射程判断结合绿色提前量点和射程圈，并要求信号持续至少 80 ms、连续至少 3 帧。开启自动开火后，满足条件即开始射击，默认持续到目标丢失超过 1 秒。火控和武器系统可以独立开关。

### 技术栈

| 技术 | 用途 |
|---|---|
| Python 3.12 | 主程序、录制回放和调试工具 |
| DXCAM / DXGI | Windows 屏幕捕获与帧时间戳 |
| OpenCV / NumPy | HUD 图像处理、特征检测和数值计算 |
| 卡尔曼滤波 | 提前量点的位置与速度估计 |
| PD 控制、速度前馈、Smith 预估 | 炮塔跟踪与延迟补偿 |
| Pydantic / YAML | 配置加载与参数校验 |
| pyserial | 主机与 Pico 的串口通信 |
| C / Pico SDK / TinyUSB | Pico 固件和 USB HID 输入 |
| Windows API | 游戏焦点检测与控制浮窗 |

各模块的处理过程见[实现原理](docs/architecture.md)，HUD 的形状、颜色和检测依据见 [HUD 笔记](docs/hud.md)。

## 安装与配置

需要准备 Pico 2 W、USB 数据线，以及安装了 Python 3.12 和 Git 的 Windows 电脑。

### 安装主程序

在 PowerShell 中执行：

```powershell
git clone https://github.com/LouieLumi/StarCitizen-AIGuner.git
cd StarCitizen-AIGuner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 编译和刷写固件

固件编译需要 ARM 工具链、Pico SDK、CMake、Ninja 和 picotool，具体步骤见[固件说明](docs/firmware.md)。

刷写完成后，设备名称为 `AI Crew Controller`。主程序根据 VID/PID 自动查找串口，无需手动填写 COM 端口。

### 配置参数

默认配置位于 [`config/config.yaml`](config/config.yaml)：

| 配置项 | 说明 |
|---|---|
| `screen` | 屏幕分辨率，默认 2560×1440 |
| `capture` | 捕获使用的显卡与显示器 |
| `roi` | HUD 检测区域，默认起点 `(680,270)`，大小 `1200×900` |
| `aim` | ROI 内的准星参考位置，检测不到准星时使用 |
| `control` | 炮塔响应模型、控制增益和鼠标位移限制 |
| `recording.dir` | 录像和事件截图目录，默认 `recordings/` |

不同分辨率还需要调整 `finder` 的排除区域、形状检测尺寸和射程圈半径。这些参数使用像素坐标，不会自动缩放。

个人配置可以保存为 `config/config.local.yaml`，启动时通过 `--config config/config.local.yaml` 指定。该文件已加入 Git 忽略规则。

## 启动与操作

进入炮塔后，将炮塔鼠标切换为 **FPS 模式**。当前控制参数按该模式标定；虚拟摇杆模式下，停止鼠标位移并不等于停止炮塔转动。

双击 **`start_gunner.bat`** 即可启动，默认同时开启火控和自动开火。程序会自动寻找目标、转向、跟踪，并在满足射程条件后开火。

控制浮窗提供两个开关：

- **火控系统**：控制自动锁定、搜索和跟踪；关闭后停止全部操作。
- **武器系统**：控制自动开火；关闭后仍可保留跟踪，手动射击。

浮窗支持拖动和位置锁定。游戏失去焦点时暂停输入，关闭控制台或按 Ctrl+C 退出程序。

也可以在项目目录中通过命令行启动：

```powershell
# 两个开关默认关闭，通过浮窗手动开启
.venv\Scripts\python.exe host\main.py

# 开启火控和自动开火，与批处理入口相同
.venv\Scripts\python.exe host\main.py --enable --auto-fire

# 运行识别和跟踪，不发送 HID 指令；无需连接 Pico
.venv\Scripts\python.exe host\main.py --dry-run --enable --seconds 30
```

程序需要在 Windows 已登录的桌面会话中运行。通过 SSH 启动时，使用[操作指南](docs/usage.md)中的 `desktop_run.ps1`。

打开聊天框前请关闭火控，避免自动锁定用的 T 被输入到聊天框。关闭火控或武器开关会停止射击；目标丢失后的停火延迟由 `fire.stop_after_unlocked_s` 设置，默认 1 秒。Pico 在 100 ms 内收不到新命令时，会释放按键、停止鼠标移动并将摇杆回中。

## 源码与调试

```text
host/                 捕获、检测、跟踪、控制和浮窗
firmware/             Pico 固件、编译和刷写脚本
config/               配置文件
tools/                录制、回放、检测调试和炮塔标定
tests/                离线测试
docs/                 实现与使用文档
logs/                 本地运行日志
recordings/           本地录像和事件截图
```

更换炮塔或调整灵敏度后，可以用 `tools/turret_ident.py` 重新测量响应延迟、平滑和增益。离线回放不需要连接 Pico，可以用同一段录制比较不同检测参数。

录像、日志和个人配置不会提交到仓库。无损录像可能每分钟占用数 GB，长时间录制前应确认可用空间。工具命令见[操作与调试](docs/usage.md)，开发环境和离线测试见[贡献说明](CONTRIBUTING.md)。

## 许可

本项目采用 [PolyForm Noncommercial 1.0.0](LICENSE)，允许符合许可条款的非商业使用、修改和分发，**不授权商业使用**。分发时请保留许可证和[版权说明](NOTICE)。

这是我的个人项目，与 CIG / RSI 无官方关联。文档中的 Star Citizen 游戏画面及商标归各自权利人所有。

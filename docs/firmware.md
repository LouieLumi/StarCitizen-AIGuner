# Pico 固件与串口协议

[返回首页](../README.md)

我使用的开发板是 Pico 2 W（RP2350），固件版本字符串为 `AI-CREW-FW 0.3.0 pico2_w`。
USB 组合设备名称为 `AI Crew Controller`：CDC 串口 + 鼠标/键盘 HID + 摇杆 HID。
VID:PID 使用开发测试值 `CAFE:4143`，主机据此自动查找串口。

## 构建环境

我的固件编译环境使用 ARM GNU Toolchain 14.3.rel1、Pico SDK 2.3.1（含 TinyUSB 子模块）、picotool 2.3.1、CMake 和 Ninja。以下步骤使用 Windows PowerShell。

需要自行安装：

- [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads)：选择面向 `arm-none-eabi` 的工具链，将 `bin` 加入 PATH。
- [CMake](https://cmake.org/download/) 和 [Ninja](https://github.com/ninja-build/ninja/releases)：可从项目虚拟环境执行 `python -m pip install cmake ninja`，并把 `.venv\Scripts` 加入 PATH。
- [Pico SDK](https://github.com/raspberrypi/pico-sdk/tree/2.3.1)：递归拉取子模块。
- [picotool](https://github.com/raspberrypi/picotool/tree/2.3.1)：UF2 生成需要。可传入包含 `picotoolConfig.cmake` 的目录；未提供时由 SDK 的 CMake 发现/获取流程处理，可能需要网络及宿主 C/C++ 构建工具。参见 [Pico 官方环境指南](https://rptl.io/pico-get-started)。

PowerShell 示例，在任意位置存放 SDK，再回到本项目根目录：

```powershell
git clone --branch 2.3.1 --recurse-submodules https://github.com/raspberrypi/pico-sdk.git ..\pico-sdk
$env:PICO_SDK_PATH = (Resolve-Path ..\pico-sdk).Path
$env:PATH = "$(Get-Location)\.venv\Scripts;$env:PATH"
powershell -ExecutionPolicy Bypass -File firmware\build.ps1
```

编译输出为 `firmware/build/ai_crew_fw.uf2`。也可通过脚本参数指定 SDK 和工具路径：

| 参数 | 作用 |
|---|---|
| `-SdkPath` | SDK 目录；默认读取环境变量 `PICO_SDK_PATH` |
| `-ToolchainBin` | 可选的 ARM 编译器 bin 目录，临时加入脚本 PATH |
| `-PicotoolDir` | 可选的 picotool CMake package 目录 |
| `-Board pico2_w` | 默认开发板；无无线芯片的 Pico 2 可用 `pico2`，需自行验证 |
| `-Clean` | 清理本项目的固件 build 目录后重新配置 |

使用其他支持的开发环境时，也可以直接运行：

```sh
cmake -S firmware -B firmware/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPICO_BOARD=pico2_w
cmake --build firmware/build
```

## 刷写与验证（Windows）

第一次刷写时按住 BOOTSEL 接入 USB，待 `RP2350` 磁盘出现：

```powershell
powershell -ExecutionPolicy Bypass -File firmware\flash.ps1
.venv\Scripts\python.exe tools\pico_test.py
```

已有本项目固件时，刷写脚本会通过串口请求 BOOTSEL。刷写后设备会重启；硬件测试在实际移动鼠标前会询问确认。附加 `--click`、`--keyboard` 或 `--joystick` 分别测试对应报告，详见[操作指南](usage.md)。

## 串口协议

每行一个 ASCII 命令，以 `\n` 或 `\r\n` 结束。USB CDC 不依赖实际波特率，主机使用 115200。数字参数按十进制发送，例如 T 的 HID 键码 `0x17` 应发送 `23`。

| 命令 | 内容 | 回复 |
|---|---|---|
| `M,dx,dy,buttons` | 相对鼠标移动；bit0 左键、bit1 右键、bit2 中键 | 无 |
| `K,modifiers,key` | 修饰键位 + 单个 HID 键码；`K,0,23` 按下 T，`K,0,0` 释放 | 无 |
| `J,x,y,z,rx,ry,rz,slider,buttons` | 7 轴，范围 -32767..32767；32 位按键掩码 | 无 |
| `STOP` | 释放输出、摇杆回中 | `OK STOP` |
| `PING` | 连通性 | `PONG` |
| `VER` | 固件版本与开发板 | `AI-CREW-FW 0.3.0 pico2_w`（默认板） |
| `STAT` | 命令、错误、超时和报告计数 | `STAT k=v ...` |
| `BOOTSEL` | 重启到 UF2 刷写模式 | `OK BOOTSEL` |

错误行回复 `ERR`。协议定义见 [`protocol.h`](../firmware/protocol.h)。

按键/摇杆是电平状态，保持输出需要持续刷新命令。固件在 100 ms 无新命令、CDC 连接断开或 USB 挂起等情况下清除输出。该保护无法把游戏内“鼠标虚拟摇杆”的虚拟光标归中；当前主程序按 FPS 鼠标模式工作。

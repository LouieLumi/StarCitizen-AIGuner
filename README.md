# StarCitizen AIGuner

[English](README.en.md) · [操作指南](docs/usage.md) · [固件与串口协议](docs/firmware.md) · [架构](docs/architecture.md)

面向 **Star Citizen 炮塔 HUD** 的外置视觉炮手实验：看屏幕、识别提前量点、跟踪目标，再通过 Raspberry Pi Pico 2 W 输出 USB HID 鼠标和键盘操作。

使用 OpenCV、卡尔曼滤波和 PD 控制，无需模型权重或云端 API。主程序通过 Windows 屏幕捕获获取画面，不读取游戏内存、不注入游戏进程。

> **源码公开 · 仅限非商业用途**。采用 [PolyForm Noncommercial 1.0.0](LICENSE)。允许符合许可的非商业使用、修改和分发；商业用途不在本许可授权范围内。它不是允许商用的标准开源许可。

![HUD 检测和跟踪示例](docs/assets/track_strip.png)

*项目已有实机录制的离线标注示例；不是跨版本、跨炮塔的效果保证。*

## 能做什么

- 识别准星、白色/绿色提前量点和射程圈，用时间滤波减少单帧误判。
- 卡尔曼跟踪结合自身转向补偿、Smith 预估和速度前馈，输出鼠标位移。
- 根据目标标签和屏幕外箭头转向，在无锁定提示时自动尝试按 T。
- 可选自动开火：满足射程条件后开始，目标丢失超过设定时间后停止。
- 浮窗分别控制火控和武器系统；游戏失去焦点时暂停操作。
- 提供日志、录制、离线回放、检测可视化、控制仿真和炮塔响应标定工具。
- Pico 固件提供 CDC 串口、鼠标/键盘 HID、预留的 7 轴 32 键摇杆 HID，以及 100 ms 无命令看门狗。

## 实现方式与技术栈

整个系统是一个视觉反馈闭环：**屏幕 → HUD 识别 → 跟踪与控制 → 串口 → Pico HID → 游戏 → 新画面**。

| 技术 | 在项目里的作用 |
|---|---|
| Python 3.12 | 主机控制循环、调试和离线分析工具 |
| DXCAM / DXGI Desktop Duplication | 捕获 Windows 游戏画面和帧时间戳 |
| OpenCV + NumPy | HSV 颜色过滤、连通域和形状分析，识别准星、提前量点与目标标记 |
| 卡尔曼滤波 | 估计目标点的位置和速度，应对短暂遮挡并排除异常观测 |
| PD 控制 + 速度前馈 | 将目标点相对准星的误差转换为鼠标位移 |
| 自身运动补偿 + Smith 预估 | 处理炮塔转动造成的画面位移，以及命令到画面响应的延迟 |
| Pydantic + YAML | 加载和校验配置，拒绝未知字段和无效参数 |
| pyserial / USB CDC | 将主机计算结果发送给 Pico |
| C + Pico SDK + TinyUSB | 在 RP2350 上实现鼠标、键盘和摇杆 HID 报告 |
| Windows API | 判断游戏前台状态、显示控制浮窗 |

检测器寻找的是游戏已经绘制的提前量点，不自行计算弹道。射程判断结合绿色提前量点和射程圈，并要求连续多帧和持续时间同时达标。找不到提前量点时，根据红色目标标签或屏幕外箭头转向，直到跟踪器接管。

控制器还会估计已经发送、但尚未在画面中体现的转向，减少延迟造成的重复修正。完整数据流和模块职责见[架构说明](docs/architecture.md)。

## 支持范围

| 部分 | 当前范围 |
|---|---|
| 实时主程序 | Windows 10/11 桌面会话，Python 3.12；需要 Pico |
| 只看屏幕的试运行 | Windows，`--dry-run`；不连接 Pico、不发送 HID |
| 离线测试与分析 | Windows / macOS / Linux；不需要游戏或 Pico |
| 默认硬件 | Pico 2 W（RP2350），USB 数据线；项目不使用 Wi-Fi |
| 默认画面 | 2560×1440、Polaris 炮塔 HUD、FPS 鼠标模式 |
| 项目状态 | 作者已完成整体实机验证并正常使用；不同分辨率、HUD、炮塔和灵敏度需要重新标定 |

## 快速开始（Windows）

先安装 Python 3.12 和 Git。从 PowerShell 执行：

```powershell
git clone https://github.com/LouieLumi/StarCitizen-AIGuner.git
cd StarCitizen-AIGuner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

按照[固件指南](docs/firmware.md)构建并刷入 Pico 固件。只做屏幕检测时可跳过硬件，使用 `--dry-run`。

编辑 [`config/config.yaml`](config/config.yaml)：确认 `screen`、`capture`、`roi` 和 `aim` 与屏幕一致。默认 ROI 为屏幕坐标 `(680,270)` 开始的 `1200×900` 区域；`aim` 使用 ROI 内坐标。其他分辨率还需调整 `finder` 排除区、形状尺寸和射程圈半径，不会自动缩放。

配置也可复制到被 Git 忽略的 `config/config.local.yaml`，随后用 `--config config/config.local.yaml` 指定。

进入游戏炮塔，切换 **FPS 鼠标模式**，在已登录的 Windows 桌面会话中运行：

```powershell
# 先试运行：识别、状态机、日志照常工作，不发送任何 HID
.venv\Scripts\python.exe host\main.py --dry-run --enable --seconds 30

# 连接 Pico，默认火控和武器开关都关闭，用浮窗开启
.venv\Scripts\python.exe host\main.py

# 明确开启自动寻找、跟踪和自动开火
.venv\Scripts\python.exe host\main.py --enable --auto-fire
```

`start_gunner.bat` 保留原有的一键启动行为：**启动即开启火控和自动开火**。它使用默认配置；自定义配置请使用上面的命令行入口。

关闭浮窗中的火控/武器开关可停止对应操作，Ctrl+C 或关闭控制台退出。也可在另一终端创建停止文件：

```powershell
New-Item logs\stop_main -ItemType File -Force
```

打开游戏聊天框前先关闭火控，避免自动发送的 T 进入聊天。虚拟摇杆鼠标模式不在当前主程序的标定范围内；该模式下停止鼠标位移不等于停止转向。

## 项目结构

```text
host/                  屏幕捕获、检测、跟踪、控制、状态机与浮窗
firmware/              Pico C / TinyUSB 固件及构建、刷写脚本
config/config.yaml     默认参数（针对已有实机环境标定）
tools/                 录制、回放、调试、仿真、硬件测试工具
tests/                 不需要硬件的合成输入与逻辑测试
docs/                  使用、架构、协议和 HUD 研究说明
logs/                  本地运行日志（不提交）
recordings/            本地录像和事件截图（不提交）
```

数据默认保存在项目内部。可把 `recording.dir` 改到其他磁盘；无损视频可能每分钟占用数 GB。分享运行数据前，请检查画面中的聊天、玩家名称和桌面内容。

## 文档与开发

- [操作与调试](docs/usage.md)：浮窗、录制、回放、标定和远程桌面会话。
- [固件与协议](docs/firmware.md)：工具链、UF2 刷写、HID 命令和看门狗。
- [架构与限制](docs/architecture.md)：数据流、模块职责和验证边界。
- [HUD 研究笔记](docs/hud.md)：基于已有录制的颜色、形状和识别依据。
- [贡献指南](CONTRIBUTING.md)：离线环境、验证和问题反馈。

GitHub Actions 在 Windows 和 Linux 上运行离线测试。它不验证游戏内捕获、真实炮塔表现或 USB 硬件，完整 Pico 固件构建和实机测试仍需对应环境。

## 许可与归属

Copyright 2026 LouieLumi。完整授权条款见 [LICENSE](LICENSE)，版权及第三方内容说明见 [NOTICE](NOTICE)。非商业范围以许可证原文为准，商业使用需另行获得权利人的明确授权。

本项目与 Cloud Imperium Games / Roberts Space Industries 无隶属或背书关系。文档中的游戏画面仅用于说明，相关游戏素材及商标归各自权利人所有，不随本项目代码重新授权。

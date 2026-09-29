# 贡献指南 / Contributing

欢迎提供可复现的问题、文档改进和代码变更。提交的原创贡献按本仓库的 [PolyForm Noncommercial 1.0.0](LICENSE) 许可提供；请保留第三方代码的原始许可及归属，不提交无权分发的素材。

Contributions are provided under this repository's noncommercial license. Preserve third-party notices and submit only material you may distribute.

## 离线开发

使用 Python 3.12。在 Windows 按首页安装；macOS / Linux：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q host tools tests
.venv/bin/python tools/controller_test.py
```

`requirements.txt` 只在 Windows 安装 DXCAM，方便其他平台运行离线逻辑。实时入口使用 Windows API，不能由此推断 macOS / Linux 支持实时运行。

pytest 仅收集 `tests/` 下的测试，避免把 `tools/pico_test.py` 等硬件诊断脚本当成自动测试。新增控制或协议行为时，优先使用合成输入或模拟串口验证。

## 提交变更

- 描述具体问题、行为变化、验证命令及结果。
- 改动配置或操作流程时同步中英文首页及对应文档。
- 标明哪些验证是离线的、哪些实际连接了 Windows 游戏或 Pico。
- 提交检测问题时附分辨率、游戏/HUD 版本和最小截图；隐藏聊天和个人信息。
- 不提交虚拟环境、SDK、编译输出、会话录像、凭据或个人配置。

在 Issue 中描述问题，或 Fork 后向 `main` 提交 Pull Request。上传大体积复现录制前，先讨论需要哪一小段数据。

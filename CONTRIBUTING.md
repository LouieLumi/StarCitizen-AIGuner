# 贡献说明

欢迎通过 Issue 反馈问题，或提交 Pull Request 改进代码与文档。检测问题请附上分辨率、炮塔类型、相关配置和能够复现问题的画面，便于定位原因。上传截图前请隐藏聊天和个人信息。

## 开发环境

项目使用 Python 3.12。Windows 环境按首页安装后，补充开发依赖并运行测试：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

macOS / Linux 可运行离线测试和回放：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/controller_test.py
```

实时捕获和浮窗依赖 Windows API。依赖文件仅在 Windows 下安装 DXCAM。

`tests/` 包含无需连接硬件的测试。`tools/pico_test.py` 会实际操作 Pico，不在 pytest 的自动收集范围内。

## 提交变更

请在 PR 中说明改动原因、行为变化和验证结果。涉及捕获或控制时，应注明使用了离线回放，还是已连接 Pico 完成游戏内测试。

配置或启动方式的变化需要同步更新文档。日志、录像、虚拟环境、SDK 和个人配置不应提交到仓库；用于复现问题的录制请尽量缩减到必要片段。

贡献代码沿用仓库的 [PolyForm Noncommercial 1.0.0](LICENSE) 许可。引用第三方代码时，请保留原始许可和归属信息。

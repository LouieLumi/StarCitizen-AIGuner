# 操作与调试指南

[返回首页](../README.md) · [固件与协议](firmware.md)

先完成首页的环境安装和配置。以下命令适用于 Windows PowerShell，均从项目根目录执行。

## 测试

在 Windows 已登录用户的桌面会话、项目根目录下运行：

```powershell
# 在项目根目录运行
.venv\Scripts\python.exe tools\pico_test.py            # 链路 + 上下左右移动 + STOP + 看门狗（会先确认）
.venv\Scripts\python.exe tools\pico_test.py --click    # 追加左键按下/松开测试
.venv\Scripts\python.exe tools\pico_test.py --joystick # 摇杆轴/按键，经 Windows WinMM 读回校验 + 看门狗回中
.venv\Scripts\python.exe tools\pico_test.py --keyboard # 键盘：按一下 F24（谁都不用的键），经 Windows 读回校验
.venv\Scripts\python.exe tools\joy_bind_helper.py --axis x   # 倒计时后摆动 X 轴，供游戏内绑定

.venv\Scripts\python.exe tools\capture_test.py                          # 预览窗口，q / Esc 退出
.venv\Scripts\python.exe tools\capture_test.py --seconds 10 --no-window # 无窗口，不抢游戏焦点
.venv\Scripts\python.exe tools\capture_test.py --record --seconds 120 --no-window   # 录制 ROI 供离线回放
```

截屏、热键、窗口只能在登录用户的桌面会话里工作。从 SSH（后台会话）运行时用 `tools\desktop_run.ps1`，
它通过计划任务 "AI Gunner Desktop Run" 把命令投递到桌面会话，默认无窗口，输出在 `logs\desktop_run.log`：

```powershell
powershell -ExecutionPolicy Bypass -File tools\desktop_run.ps1 -Command ".venv\Scripts\python.exe tools\capture_test.py --seconds 10 --no-window"
powershell -ExecutionPolicy Bypass -File tools\desktop_run.ps1 -Remove   # 删除该计划任务
```

## AI 炮手主程序

日常使用：进炮塔后双击 `start_gunner.bat`（= `--enable --auto-fire`）。之后全自动：
没有锁定目标 2 s 自动按 T → 转向目标 → 跟踪 → 变绿开火 → 锁定丢失 1 s 停火 → 再按 T。

浮窗控制面板（半透明黑底，始终置顶，点击不抢游戏焦点）：
- **火控系统**：开 = 自动锁定 / 寻找 / 跟踪；关 = 全部停止（也会解除急停）
- **武器系统**：开 = 进入射程自动开火；关 = 不开火（火控关着时也会记住这个选择）
- 右上角的锁：开锁时可拖动，点一下固定位置；位置和锁定状态存在 `logs\panel.json`
- 最下面一行是状态；游戏不在前台时变红，此时不移动鼠标、不开火、不按键
- `--no-panel` 不显示浮窗

没有键盘快捷键，全部用浮窗控制。关控制台窗口 = 退出程序。
打开聊天框前先把火控关掉，否则自动按的 T 会打进聊天框。

```powershell
.venv\Scripts\python.exe host\main.py --enable --auto-fire   # 两个开关都开（start_gunner.bat）
.venv\Scripts\python.exe host\main.py              # 两个开关都关，在浮窗里打开
.venv\Scripts\python.exe host\main.py --dry-run    # 全流程运行但绝不动鼠标
```

只有"有目标轨迹 + 0.3 秒内看到准星"时才会移动鼠标，所以菜单里、离开炮塔时不会动。
没有目标轨迹时（ARMED / SEARCHING），会朝游戏里锁定（T）的目标转过去，找到提前量点后交给跟踪。

炮塔响应标定（改了游戏灵敏度、换了炮塔后重做）：

```powershell
.venv\Scripts\python.exe host\main.py --enable --dither 12 --seconds 180   # 照常按 T 锁定；跟踪时叠加 ±12 计数随机抖动
.venv\Scripts\python.exe tools\turret_ident.py logs\session_....csv        # 算出延迟 / 平滑 / 增益，填进 config 的 control 段
```
远程停止：创建 `logs\stop_main`。每帧写入 `logs\session_*.csv`，关键事件截图存放于 `recording.dir` 下。

## 离线工具（不发送任何 HID）

```powershell
.venv\Scripts\python.exe tools\record_session.py                 # 录整局（全屏 MJPG + 每 5 秒无损截图），停止：PowerShell 运行 New-Item logs\stop_record -ItemType File -Force
.venv\Scripts\python.exe tools\replay.py <session目录> --video     # 检测 + 跟踪回放，输出统计、CSV、标注视频
.venv\Scripts\python.exe tools\detector_debug.py still.png         # 单图：原图 / HSV / 形状掩码 / 绿色掩码
.venv\Scripts\python.exe tools\controller_test.py [--latency 5 --smoothing 0.6] [--sweep]  # 控制器 + 真实跟踪器在模拟炮塔上的表现
.venv\Scripts\python.exe tools\track_replay.py logs\session_*.csv [--grid]  # 用实机日志回放跟踪器，比较参数（断跟、跳变）
.venv\Scripts\python.exe tests\test_detector.py                    # 另有 test_tracker / test_search / test_state_machine / test_own_motion / test_weapon_range
```

## 配置

`config\config.yaml`：屏幕分辨率、捕获设备、ROI、录制目录。
录制默认写入项目内的 `recordings/`，可通过 `recording.dir` 改为其他磁盘的绝对路径。无损 FFV1 录制可能每分钟占用数 GB。

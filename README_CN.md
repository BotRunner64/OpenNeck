# 简化主动视觉驱动

这是一个独立的新实现，按 LeRobot/SO-101 那种流程组织。舵机通信使用官方
`ftservo/FTServo_Python` 的 pip 包：

```bash
pip install ftservo-python-sdk==2.0.0
```

代码里直接使用它提供的 `scservo_sdk` API：`PortHandler -> sms_sts -> WritePosEx / ReadPosSpeed`。
不使用 `vassar-feetech-servo-sdk`。

```text
ports -> calibrate -> center/test -> run
```

## 安装

```bash
cd simple_active_vision_driver
pip install -r requirements.txt
```

`requirements.txt` 已包含 PicoBridge wheel：

```text
https://github.com/BotRunner64/pico-bridge/releases/download/v0.2.1/pico_bridge-0.2.1-py3-none-any.whl
```

## 串口权限

Linux 如果报 `Permission denied: '/dev/ttyACM0'`：

```bash
sudo usermod -a -G dialout $USER
```

然后重新登录或重启。临时修复：

```bash
sudo chmod 666 /dev/ttyACM0
```

## 标准流程

1. 找串口：

```bash
python simple_active_vision.py ports
```

2. 校准物理正前方和两个轴的安全极值：

```bash
python simple_active_vision.py calibrate --port /dev/ttyACM0
```

程序会释放舵机扭矩，然后按三步采样：

```text
1. 手动把相机摆到物理正前方，按 Enter
2. 只移动 yaw 轴，通过完整安全范围，按 Enter
3. 只移动 pitch 轴，通过完整安全范围，按 Enter
```

不要硬掰机构，只走你认为安全的范围。配置会保存到：

```text
active_vision_config.json
```

3. 验证回中：

```bash
python simple_active_vision.py center
```

`center` 退出时不会关闭舵机扭矩，pitch 轴会保持住。

4. 单轴小步测试。先用小步长确认没有乱转：

```bash
python simple_active_vision.py test yaw --step 30
python simple_active_vision.py test pitch --step 30
```

5. 运行主动视觉：

```bash
python simple_active_vision.py run
```

如果 pitch 一运行就冲到极限，先不要让舵机动，做 dry-run：

```bash
python simple_active_vision.py run --dry-run --no-camera
```

看输出里的 `cmd=(yaw,pitch)` 和 `target={...}`。如果 pitch 命令符号反了：

```bash
python simple_active_vision.py run --no-invert-pitch --no-camera
```

如果 pitch 幅度过大，先限制范围：

```bash
python simple_active_vision.py run --pitch-limit 0.25 --no-camera
```

只跑云台和 PICO，不开 RealSense：

```bash
python simple_active_vision.py run --no-camera
```

## 常用配置覆盖

```bash
python simple_active_vision.py calibrate --port /dev/ttyACM0 --yaw-id 1 --pitch-id 2
python simple_active_vision.py center --speed 40 --acceleration 60
python simple_active_vision.py run --no-body
```

查看当前配置：

```bash
python simple_active_vision.py config
```

配置里应包含：

```json
{
  "yaw_center": 2048,
  "yaw_min": 1200,
  "yaw_max": 2900,
  "pitch_center": 2048,
  "pitch_min": 1600,
  "pitch_max": 2500
}
```

## 运行时命令

运行 `run` 后，在同一个终端输入：

```text
c    # 重新以当前头部方向校准
q    # 退出
```

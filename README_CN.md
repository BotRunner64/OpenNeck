# OpenNeck 主动视觉驱动

OpenNeck 是一个两轴头颈云台主动视觉驱动。舵机通信使用 `ftservo-python-sdk` 提供的 `scservo_sdk`，不依赖外部 RoboController 项目。

整体流程：

```text
安装依赖 -> 接线上电 -> 找串口 -> 检查舵机 -> 改 ID/2048 中位 -> OpenNeck 校准 -> 回中/小步测试 -> dry-run -> 正式运行
```

## 1. 安装

```bash
cd OpenNeck
pip install -r requirements.txt
```

`requirements.txt` 已包含：

- `ftservo-python-sdk==2.0.0`
- `pyserial`
- `numpy`
- `pyrealsense2`
- PicoBridge wheel

## 2. 接线和上电

先确认硬件：

- 舵机电源电压和舵机型号匹配。
- USB 只负责通信，不给舵机供电。
- yaw 和 pitch 都接到同一条舵机总线。
- 默认 ID 约定是 `yaw=1`、`pitch=2`。
- 断电时云台能手动通过安全范围，没有卡死、撞限位、拉线。

Linux 如果没有串口权限：

```bash
sudo usermod -a -G dialout $USER
```

重新登录后生效。临时调试可以用：

```bash
sudo chmod 666 /dev/ttyACM0
```

## 3. 找串口

```bash
python simple_active_vision.py ports
```

常见端口是 `/dev/ttyACM0` 或 `/dev/ttyUSB0`。后续示例假设端口是：

```bash
export OPENNECK_PORT=/dev/ttyACM0
```

## 4. 检查舵机通信

先只读电压和位置，不让云台运动：

```bash
python simple_active_vision.py voltage --port "$OPENNECK_PORT" --yaw-id 1 --pitch-id 2
```

两个舵机都能读到电压和位置后再继续。如果读不到：

- 检查电源是否接上。
- 检查三针线方向和接触。
- 检查 ID 是否是 `1` 和 `2`。
- 检查串口权限。

也可以用本地工具扫描总线：

```bash
python tools/scan_servos.py --port "$OPENNECK_PORT"
```

期望看到：

```text
[scan] found ids=[1, 2]
```

## 5. 改舵机 ID

第一次运行必须完成 ID 校准。默认 ID 约定是 `yaw=1`、`pitch=2`。改 ID 会写入舵机内部非易失配置，断电后仍然保留。

改 ID 时总线上只接一个目标舵机。

只接 yaw 舵机，把它改成 ID 1：

```bash
python tools/change_servo_id.py --port "$OPENNECK_PORT" --new-id 1
```

只接 pitch 舵机，把它改成 ID 2：

```bash
python tools/change_servo_id.py --port "$OPENNECK_PORT" --new-id 2
```

改完后两个舵机都接回总线，再扫描确认：

```bash
python tools/scan_servos.py --port "$OPENNECK_PORT"
```

## 6. 做 2048 中位校准

`2048 中位校准` 是舵机内部校准：把当前机械姿态写成舵机自己的中位值 `2048`。
第一次运行必须完成 2048 中位校准。

执行：

```bash
python tools/calibrate_servo_middle.py --port "$OPENNECK_PORT" --ids 1 2
```

脚本会：

1. 关闭力矩。
2. 提示你手动把 yaw/pitch 放到期望机械中位。
3. 把当前位置写成舵机内部 `2048`。
4. 移动到 `2048` 做验证。

如果云台移动到 `2048` 后回到预期中位，说明硬件中位正常。

## 7. OpenNeck 校准

这一步不是 2048 中位校准。它只生成 OpenNeck 运行配置 `active_vision_config.json`。

```bash
python simple_active_vision.py calibrate --port "$OPENNECK_PORT" --yaw-id 1 --pitch-id 2
```

按提示完成：

```text
1. 手动把相机摆到物理正前方，按 Enter
2. 只移动 yaw 轴，通过完整安全范围，按 Enter
3. 只移动 pitch 轴，通过完整安全范围，按 Enter
```

注意：

- 每次只动一个轴。
- 不要硬掰机构。
- 不要把线缆拉到极限。
- 只记录你愿意让程序自动运行的安全范围。

配置会保存到：

```text
active_vision_config.json
```

## 8. 回中验证

先分别验证两个轴：

```bash
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis yaw --hold-s 2
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis pitch --hold-s 2
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis both --hold-s 2
```

确认：

- yaw 命令只动水平轴。
- pitch 命令只动俯仰轴。
- `both` 能回到物理正前方。

## 9. 小步测试

先用小步长和低速度测试，不要一开始就跑主动视觉：

```bash
python simple_active_vision.py test yaw --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
python simple_active_vision.py test pitch --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
```

确认没有撞限位、抖动、线缆拉扯。

## 10. Dry-run

先读取 PICO 姿态并打印目标，不驱动舵机：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --dry-run --no-camera
```

观察输出里的 `cmd=(yaw,pitch)` 和 `target={...}`。如果 pitch 方向反了，可以试：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --dry-run --no-camera --no-invert-pitch
```

## 11. 正式运行

第一次闭环运行先限制幅度：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.25 --pitch-limit 0.25 --speed 40 --acceleration 60
```

稳定后逐步放大：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.5 --pitch-limit 0.4
python simple_active_vision.py run --port "$OPENNECK_PORT"
```

运行中可以在同一个终端输入：

```text
c    # 重新以当前头部方向校准
q    # 退出
```

## 常用命令

查看当前配置：

```bash
python simple_active_vision.py config
```

只跑云台和 PICO，不开 RealSense：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-camera
```

pitch 幅度过大时先限制：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --pitch-limit 0.25 --no-camera
```

不使用身体姿态，只用头部姿态：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-body
```

## 校准区别

两种校准不要混淆：

- `tools/calibrate_servo_middle.py`：硬件级 2048 中位校准，会写入舵机内部配置。
- `simple_active_vision.py calibrate`：OpenNeck 运行配置校准，只保存 `active_vision_config.json`。

第一次运行必须先完成 ID 校准和 2048 中位校准，再做 OpenNeck 校准。

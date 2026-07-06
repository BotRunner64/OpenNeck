# OpenNeck

两轴头颈云台主动视觉驱动。核心包只包含云台驱动和维护工具，`pico-bridge` 不放进核心依赖。

## 安装

```bash
pip install .
```

需要 PICO 闭环运行时再装：

```bash
pip install '.[pico]'
```

Linux 没有串口权限时：

```bash
sudo usermod -a -G dialout $USER
```

重新登录后生效。临时调试可以用：

```bash
sudo chmod 666 /dev/ttyACM0
```

## 使用流程

1. 所有配件装配好，确认云台断电时能在安全范围内手动活动，没有卡死、撞限位或拉线。

2. 找串口：

```bash
openneck ports
export OPENNECK_PORT=/dev/ttyACM0
```

3. 只连接 yaw 电机，设置 ID 为 1：

```bash
openneck-change-servo-id --port "$OPENNECK_PORT" --new-id 1
```

4. 只连接 pitch 电机，设置 ID 为 2：

```bash
openneck-change-servo-id --port "$OPENNECK_PORT" --new-id 2
```

5. 同时连接 yaw 和 pitch，扫描 ID 和电压，确保正常：

```bash
openneck-scan-servos --port "$OPENNECK_PORT"
```

期望看到：

```text
[scan] found ids=[1, 2]
```

6. 将 yaw 和 pitch 摆到物理中位，写入舵机 2048 中位：

```bash
openneck-calibrate-middle --port "$OPENNECK_PORT" --ids 1 2
```

7. 测量 OpenNeck 逻辑中位和极值。按照提示先移动到物理正前方，再分别只移动 yaw 和 pitch 通过安全范围：

```bash
openneck calibrate --port "$OPENNECK_PORT"
```

8. 回中验证：

```bash
openneck center --port "$OPENNECK_PORT" --axis both --hold-s 2
```

9. 小步测试：

```bash
openneck test yaw --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
openneck test pitch --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
```

10. 戴好 PICO，先 dry-run：

```bash
openneck run --port "$OPENNECK_PORT" --dry-run --no-camera
```

11. 正式运行先限制幅度：

```bash
openneck run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.25 --pitch-limit 0.25 --speed 40 --acceleration 60
```

稳定后：

```bash
openneck run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.5 --pitch-limit 0.4
openneck run --port "$OPENNECK_PORT"
```

运行中输入：

```text
c    重新以当前头部方向校准
q    退出
```

## 常用命令

```bash
openneck config
openneck voltage --port "$OPENNECK_PORT"
openneck run --port "$OPENNECK_PORT" --no-camera
openneck run --port "$OPENNECK_PORT" --pitch-limit 0.25 --no-camera
openneck run --port "$OPENNECK_PORT" --no-body
```

## 程序调用

其他 Python 项目可以直接调用控制器 API：

```python
from openneck import OpenNeckController

with OpenNeckController(port="/dev/ttyACM0") as neck:
    neck.center()
    neck.move_norm(yaw=0.2, pitch=-0.1)
    print(neck.read_positions())
```

也可以指定校准配置文件：

```python
from openneck import OpenNeckController

with OpenNeckController(config="active_vision_config.json") as neck:
    neck.move_norm(0.0, 0.0)
```

## 校准区别

- `openneck-calibrate-middle`：硬件级 2048 中位校准，会写入舵机内部配置。
- `openneck calibrate`：OpenNeck 运行配置校准，只保存 `active_vision_config.json`。

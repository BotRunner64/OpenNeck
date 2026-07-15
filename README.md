# OpenNeck

两轴头颈云台驱动。主要控制 API 只接受相对机械中位的角度：

- `yaw_deg = 0`：正前方
- `yaw_deg > 0`：向左
- `yaw_deg < 0`：向右
- `pitch_deg = 0`：水平
- `pitch_deg > 0`：向上
- `pitch_deg < 0`：向下

Teleopit 负责把人体姿态转换为机器人目标角度；OpenNeck 只负责把目标角度转换为舵机位置，并执行标定后的机械限位。

## 安装

```bash
pip install .
```

Linux 没有串口权限时：

```bash
sudo usermod -a -G dialout $USER
```

重新登录后生效。临时调试可以使用：

```bash
sudo chmod 666 /dev/ttyACM0
```

## 配置

默认从当前目录的 `active_vision_config.json` 读取配置，也可以在 API 或 CLI 中指定其他文件：

```json
{
  "port": "/dev/ttyACM0",
  "baudrate": 1000000,
  "yaw_id": 1,
  "pitch_id": 2,
  "yaw_center_step": 2048,
  "yaw_min_step": 1024,
  "yaw_max_step": 3072,
  "yaw_step_sign": 1,
  "pitch_center_step": 2048,
  "pitch_min_step": 1365,
  "pitch_max_step": 2731,
  "pitch_step_sign": 1,
  "speed": 0,
  "acceleration": 0
}
```

`yaw_step_sign` 和 `pitch_step_sign` 只允许为 `1` 或 `-1`：

- 逻辑正角度使舵机 step 增大时填 `1`。
- 逻辑正角度使舵机 step 减小时填 `-1`。

机械安装方向完全由这两个字段吸收，上层调用始终使用相同的左正、上正约定。配置包含未知字段时会直接报错，避免错误配置被静默接受。

从 `0.1.x` 升级时需要重新运行 `openneck calibrate`。旧配置中的归一化幅度和姿态反向字段不能安全推导新的物理角度方向，因此 `0.2.x` 不会自动转换旧配置；请先备份或移走旧文件，再按实际安装方向设置两个 `*_step_sign` 字段。

## Python API

包根目录只公开 `NeckAngles` 和 `OpenNeckController`：

```python
from openneck import OpenNeckController

with OpenNeckController(
    config="active_vision_config.json",
    port="/dev/ttyACM0",
) as neck:
    applied = neck.move_deg(yaw_deg=30.0, pitch_deg=-15.0)
    print(applied)
    print(neck.read_deg())
    print(neck.read_voltage())
```

`move_deg()` 返回经过机械限位裁剪和舵机整数 step 量化后的实际目标角度。它表示已发送的目标，不是位置回读；需要当前位置时调用 `read_deg()`。

不使用上下文管理器时，可以显式管理连接：

```python
from openneck import OpenNeckController

neck = OpenNeckController(port="/dev/ttyACM0")
try:
    neck.connect()
    neck.center()
    neck.move_deg(yaw_deg=-20.0, pitch_deg=10.0)
    neck.release_torque()
finally:
    neck.close()
```

`close()` 只关闭串口，不改变当前扭矩状态；需要释放保持力时应显式调用 `release_torque()`。

## 装配与标定

1. 确认云台断电时能在安全范围内手动活动，没有卡死、撞限位或拉线。

2. 查找串口：

```bash
openneck ports
export OPENNECK_PORT=/dev/ttyACM0
```

3. 只连接 yaw 电机并设置 ID 为 1：

```bash
openneck-change-servo-id --port "$OPENNECK_PORT" --new-id 1
```

4. 只连接 pitch 电机并设置 ID 为 2：

```bash
openneck-change-servo-id --port "$OPENNECK_PORT" --new-id 2
```

5. 同时连接两个电机并检查 ID 与电压：

```bash
openneck-scan-servos --port "$OPENNECK_PORT"
```

6. 将两个轴摆到硬件中位并写入舵机内部的 2048 中位：

```bash
openneck-calibrate-middle --port "$OPENNECK_PORT" --ids 1 2
```

7. 标定 OpenNeck 的逻辑中位和安全机械范围，并按安装方向指定符号：

```bash
openneck calibrate \
  --port "$OPENNECK_PORT" \
  --yaw-step-sign 1 \
  --pitch-step-sign 1
```

该命令把结果写入 `active_vision_config.json`。原始位置读写只存在于这些包内维护与标定工具中。

8. 回中并做小角度验证：

```bash
openneck center --port "$OPENNECK_PORT" --hold-s 2
openneck test yaw --port "$OPENNECK_PORT" --angle-deg 5
openneck test pitch --port "$OPENNECK_PORT" --angle-deg 5
```

## 其他命令

```bash
openneck config
openneck voltage --port "$OPENNECK_PORT"
```

`openneck-calibrate-middle` 修改舵机内部的非易失硬件中位；`openneck calibrate` 只更新 OpenNeck 的 JSON 运行配置。

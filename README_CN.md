# 简化主动视觉驱动

这是一个独立的新实现，按 LeRobot/SO-101 那种流程组织。舵机通信使用官方
`ftservo/FTServo_Python` 的 pip 包：

```bash
pip install ftservo-python-sdk==2.0.0
```

代码里直接使用它提供的 `scservo_sdk` API：`PortHandler -> sms_sts -> WritePosEx / ReadPosSpeed`。
不使用 `vassar-feetech-servo-sdk`。

```text
ports -> voltage/health -> calibrate -> center -> test -> dry-run -> run
```

## 安装

```bash
cd OpenNeck
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

## 设计依据

OpenNeck 的校准流程参考了两类上游流程，但只保留与两轴头颈云台相关的部分：

- Seeed SO-ARM10x 文档把校准拆成两层：散件阶段的舵机 ID/中位准备，以及装好后的整机运动范围校准。组装版可以跳过散件舵机配置，直接做整机校准。
- Seeed RoboController 提供了舵机 ID 扫描、力矩关闭、中位写入 2048、中位测试、LeRobot 风格整机校准等工具。OpenNeck 不生成 LeRobot 校准文件，而是把自己的 yaw/pitch 物理正前方和安全极限保存到 `active_vision_config.json`。

参考：

- [Seeed SO-ARM10x 校准舵机并组装机械臂](https://wiki.seeedstudio.com/cn/lerobot_so100m_new/#%E6%A0%A1%E5%87%86%E8%88%B5%E6%9C%BA%E5%B9%B6%E7%BB%84%E8%A3%85%E6%9C%BA%E6%A2%B0%E8%87%82)
- [Seeed_RoboController 使用文档](https://github.com/Seeed-Projects/Seeed_RoboController#-%E4%BD%BF%E7%94%A8%E6%96%87%E6%A1%A3)

## 完整硬件校准流程

这个流程从 OpenNeck 机械结构已经组装完成、两个舵机已经接入同一条总线开始。不要把 `calibrate` 当作第一条命令直接运行；先确认供电、串口、ID 和读数都正常，再释放力矩采样机械安全范围。

术语先区分清楚：

- `2048 中位校准` 是舵机内部校准：把当前机械姿态写成舵机自己的中位值 2048。这个步骤由 Seeed_RoboController 的 `servo_middle_calibration.py` 完成，OpenNeck 平时不需要重复做。
- `OpenNeck calibrate` 是运行配置校准：记录当前物理正前方和 yaw/pitch 安全范围，保存到 `active_vision_config.json`。它不会修改舵机内部 2048 中位。

### 0. 上电前检查

1. 确认云台可以在断电状态下手动通过完整安全范围，没有卡死、顶线或撞限位。
2. 确认舵机电源电压与舵机型号匹配；USB 只负责通信，不给舵机供电。
3. 确认 yaw 和 pitch 的三针线方向一致，电源地和控制板共地。
4. 默认约定 `yaw_id=1`、`pitch_id=2`。如果你换过舵机或总线里还有其他舵机，先用 Seeed_RoboController 扫描/修改 ID。

可选的 ID 扫描：

```bash
git clone https://github.com/Seeed-Projects/Seeed_RoboController.git
cd Seeed_RoboController
pip install -r requirements.txt
python -m src.tools.scan_id --list
python -m src.tools.scan_id /dev/ttyACM0
```

期望结果：同一端口只看到两个目标舵机，ID 分别为 `1` 和 `2`。

### 1. 找到 OpenNeck 串口

```bash
python simple_active_vision.py ports
```

Linux 常见端口是 `/dev/ttyACM0` 或 `/dev/ttyUSB0`。如果串口存在但打不开，优先做永久权限配置：

```bash
sudo usermod -a -G dialout $USER
```

然后重新登录。临时调试可以使用：

```bash
sudo chmod 666 /dev/ttyACM0
```

后续命令都用同一个端口，例如：

```bash
export OPENNECK_PORT=/dev/ttyACM0
```

### 2. 通信和供电健康检查

先只读电压和位置，不让云台运动：

```bash
python simple_active_vision.py voltage --port "$OPENNECK_PORT" --yaw-id 1 --pitch-id 2
```

通过标准：

- 两个 ID 都能 ping/read。
- 电压读数符合你的供电规格，且两个舵机读数接近。
- 位置值在 `0..4095`，不会出现异常大值、无状态包、频繁超时。

如果这里失败，不要继续校准：

- `Permission denied`：修复串口权限。
- `There is no status packet` 或读不到某个 ID：检查电源、三针线、ID 是否冲突。
- 读数异常或之前发生过撞限位：先断电重上电；仍异常时，用 Seeed_RoboController 做 2048 中位校准。

### 3. 必要时重做舵机 2048 中位

只有在这些情况下才需要做这一步：换过舵机、改过齿轮/舵盘装配、回中明显偏离、位置读数异常、运行中出现超大角度/偏移报错。

用 Seeed_RoboController 的顺序是：

```bash
cd Seeed_RoboController
python -m src.tools.servo_disable /dev/ttyACM0
```

手动把 yaw、pitch 放到你希望的机械中位，再写入当前位置为 2048：

```bash
python -m src.tools.servo_middle_calibration /dev/ttyACM0
python -m src.tools.servo_center_test /dev/ttyACM0
```

验证标准：`servo_center_test` 移动到 2048 后，云台应该回到预期的物理中位附近。完成后回到 OpenNeck 目录。

### 4. OpenNeck 物理正前方和安全范围校准

这一步会保存 OpenNeck 运行真正使用的配置：

```bash
python simple_active_vision.py calibrate --port "$OPENNECK_PORT" --yaw-id 1 --pitch-id 2
```

程序会先连接舵机，然后释放力矩。按提示完成三段采样：

```text
1. 手动把相机摆到物理正前方，按 Enter
2. 只移动 yaw 轴，通过完整安全范围，按 Enter
3. 只移动 pitch 轴，通过完整安全范围，按 Enter
```

采样要求：

- 每次只动一个轴，另一个轴尽量保持不动。
- 不要硬掰机构，不要把线缆拉到极限；只记录你愿意让程序自动运行的安全范围。
- yaw/pitch 的 center 必须落在 min/max 中间；如果脚本报范围太小或 center 不在范围内，重新执行本步骤。

配置保存到：

```text
active_vision_config.json
```

### 5. 分阶段回中验证

先分别回中，确认轴映射没有写反：

```bash
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis yaw --hold-s 2
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis pitch --hold-s 2
python simple_active_vision.py center --port "$OPENNECK_PORT" --axis both --hold-s 2
```

通过标准：

- yaw 命令只影响水平轴。
- pitch 命令只影响俯仰轴。
- `both` 能回到物理正前方。
- 读回位置稳定，没有持续往机械限位顶。

### 6. 小步运动测试

先用低速度、小步长测试，不要一开始就跑主动视觉：

```bash
python simple_active_vision.py test yaw --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
python simple_active_vision.py test pitch --port "$OPENNECK_PORT" --step 30 --speed 40 --acceleration 60
```

通过标准：

- `center -> +step -> -step -> center` 的方向符合预期。
- 两个方向都没有撞限位、抖动或线缆拉扯。
- 如果方向不符合直觉，先不要改硬件；在 `run` 阶段用 `--invert-yaw/--no-invert-yaw`、`--invert-pitch/--no-invert-pitch` 调整头部映射方向。

### 7. 主动视觉 dry-run

先读取 PICO 姿态并打印目标，不驱动舵机：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --dry-run --no-camera
```

戴上或移动 PICO，观察输出里的 `cmd=(yaw,pitch)` 和 `target={...}`：

- 头向左/右时，yaw 命令应连续、平滑、符号可解释。
- 低头/抬头时，pitch 命令应连续、平滑、不会瞬间打满。
- 如果 pitch 符号反了，先试：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --dry-run --no-camera --no-invert-pitch
```

### 8. 低幅度闭环运行

第一次让舵机跟随时，限制幅度：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.25 --pitch-limit 0.25 --speed 40 --acceleration 60
```

确认稳定后再逐步放大：

```bash
python simple_active_vision.py run --port "$OPENNECK_PORT" --no-camera --yaw-limit 0.5 --pitch-limit 0.4
python simple_active_vision.py run --port "$OPENNECK_PORT"
```

运行中可以在同一个终端输入：

```text
c    # 重新以当前头部方向校准
q    # 退出
```

### 9. 校准完成标准

完成后检查：

```bash
python simple_active_vision.py config
```

配置里应包含合理的中心和范围，例如：

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

验收标准：

- `voltage` 能稳定读到两个舵机。
- `center --axis yaw/pitch/both` 均能回到预期姿态。
- `test yaw/pitch --step 30` 不撞限位。
- `run --dry-run --no-camera` 输出连续、方向明确。
- 低幅度 `run --no-camera --yaw-limit 0.25 --pitch-limit 0.25` 稳定后，才允许全幅运行。

## 快速流程

1. 找串口：

```bash
python simple_active_vision.py ports
```

2. 做通信和供电检查：

```bash
python simple_active_vision.py voltage --port /dev/ttyACM0
```

3. 校准物理正前方和两个轴的安全极值：

```bash
python simple_active_vision.py calibrate --port /dev/ttyACM0
```

这是 OpenNeck 运行配置校准，不是舵机内部 2048 中位校准。

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

4. 验证回中：

```bash
python simple_active_vision.py center
```

`center` 退出时不会关闭舵机扭矩，pitch 轴会保持住。

5. 单轴小步测试。先用小步长确认没有乱转：

```bash
python simple_active_vision.py test yaw --step 30
python simple_active_vision.py test pitch --step 30
```

6. 运行主动视觉：

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

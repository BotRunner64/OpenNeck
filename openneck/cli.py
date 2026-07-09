#!/usr/bin/env python3
"""Small active-vision driver, organized like a simple robot CLI.

Typical flow:
  openneck ports
  openneck calibrate --port /dev/ttyACM0
  openneck center
  openneck run
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


CONFIG_PATH = Path.cwd() / "active_vision_config.json"
SERVO_MIN = 0
SERVO_MAX = 4095
TORQUE_ENABLE_ADDR = 40
PRESENT_VOLTAGE_ADDR = 62
CALIBRATION_DISPLAY_PERIOD_S = 0.1
CALIBRATION_SAMPLE_PERIOD_S = 0.02
CALIBRATION_MAX_STEP_JUMP = 400


@dataclass
class Config:
    port: str | None = None
    baudrate: int = 1_000_000
    servo_type: str = "sts"
    yaw_id: int = 1
    pitch_id: int = 2
    yaw_center: int = 2048
    pitch_center: int = 2048
    yaw_min: int = 1024
    yaw_max: int = 3072
    pitch_min: int = 1365
    pitch_max: int = 2731
    yaw_range_deg: float = 90.0
    pitch_range_deg: float = 60.0
    yaw_limit: float = 0.85
    pitch_limit: float = 0.85
    invert_yaw: bool = True
    invert_pitch: bool = True
    speed: int = 0
    acceleration: int = 0

    def axis_target(self, axis: str, value: float) -> int:
        value = float(np.clip(value, -1.0, 1.0))
        if axis == "yaw":
            center, low, high = self.yaw_center, self.yaw_min, self.yaw_max
        else:
            center, low, high = self.pitch_center, self.pitch_min, self.pitch_max
        if value >= 0:
            pos = center + value * (high - center)
        else:
            pos = center + value * (center - low)
        return int(np.clip(round(pos), low, high))


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    base = asdict(Config())
    base.update({key: value for key, value in data.items() if key in base})
    return Config(**base)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
        f.write("\n")
    print(f"[config] saved {path}")


def with_overrides(args) -> Config:
    cfg = load_config(Path(args.config))
    for key in [
        "port",
        "baudrate",
        "servo_type",
        "yaw_id",
        "pitch_id",
        "yaw_center",
        "pitch_center",
        "yaw_min",
        "yaw_max",
        "pitch_min",
        "pitch_max",
        "yaw_limit",
        "pitch_limit",
        "invert_yaw",
        "invert_pitch",
        "speed",
        "acceleration",
    ]:
        value = getattr(args, key, None)
        if value is not None:
            setattr(cfg, key, value)
    return cfg


def find_servo_port() -> str:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    preferred = [
        port.device
        for port in ports
        if "ttyACM" in port.device or "ttyUSB" in port.device or port.device.startswith("COM")
    ]
    if preferred:
        return preferred[0]
    if ports:
        return ports[0].device
    raise RuntimeError("no serial ports found; pass --port explicitly")


class Gimbal:
    def __init__(self, cfg: Config, enable_torque_on_connect: bool = True):
        from scservo_sdk import COMM_SUCCESS, PortHandler, sms_sts

        self.cfg = cfg
        self.ids = [cfg.yaw_id, cfg.pitch_id]
        self.comm_success = COMM_SUCCESS
        self.port_name = cfg.port or find_servo_port()
        self.port = PortHandler(self.port_name)
        self.packet = sms_sts(self.port)
        self.opened = False
        self.connected = False
        self.enable_torque_on_connect = enable_torque_on_connect

    def __enter__(self):
        try:
            if not self.port.openPort():
                raise RuntimeError(f"failed to open port {self.port_name}")
            self.opened = True
            if not self.port.setBaudRate(self.cfg.baudrate):
                self.opened = False
                raise RuntimeError(f"failed to set baudrate {self.cfg.baudrate}")
            print(
                f"[servo] opening port={self.port_name} baudrate={self.cfg.baudrate} "
                f"ids={self.ids} torque_on_connect={self.enable_torque_on_connect}"
            )
            for sid in self.ids:
                self.ping(sid)
                voltage = self.read_voltage(sid)
                print(f"[servo] id={sid} voltage={voltage:.1f}V")
                if self.enable_torque_on_connect:
                    self.enable_torque(sid)
        except Exception as exc:
            message = str(exc)
            self.close()
            if "Permission denied" in message and "/dev/tty" in message:
                raise SystemExit(
                    f"Cannot open servo port: {message}\n"
                    "Fix permanently: sudo usermod -a -G dialout $USER, then re-login.\n"
                    "Temporary fix: sudo chmod 666 /dev/ttyACM0"
                ) from exc
            if "Input voltage error" in message:
                raise SystemExit(
                    f"{message}\n"
                    "Servo reported an input-voltage fault. Stop motion and check hardware before retrying:\n"
                    "  1. Check the servo power supply voltage and current capacity.\n"
                    "  2. Check ID2/pitch servo wiring, connectors, and common ground.\n"
                    "  3. Move the pitch axis away from the mechanical stop by hand with power off.\n"
                    "  4. Power-cycle the servo bus, then run: openneck ports / center.\n"
                    "Do not bypass this error in software."
                ) from exc
            raise
        self.connected = True
        print(f"[servo] connected ids={self.ids} port={self.port_name}")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        if not self.opened:
            return
        self.opened = False
        self.connected = False

    def ping(self, motor_id: int, attempts: int = 3) -> int:
        last_exc: RuntimeError | None = None
        for attempt in range(1, attempts + 1):
            model, comm, err = self.packet.ping(motor_id)
            try:
                self._check(comm, err, f"ping servo {motor_id}")
                return int(model)
            except RuntimeError as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(0.08)
        assert last_exc is not None
        raise last_exc

    def read(self) -> dict[int, int]:
        return {sid: self.read_one(sid) for sid in self.ids}

    def read_one(self, motor_id: int) -> int:
        pos, _speed, comm, err = self.packet.ReadPosSpeed(motor_id)
        self._check(comm, err, f"read servo {motor_id}")
        pos = int(pos)
        if pos < SERVO_MIN or pos > SERVO_MAX:
            raise RuntimeError(f"read servo {motor_id}: invalid position {pos}")
        return pos

    def read_voltage(self, motor_id: int) -> float:
        voltage_raw, comm, err = self.packet.read1ByteTxRx(motor_id, PRESENT_VOLTAGE_ADDR)
        if comm != self.comm_success:
            raise RuntimeError(f"read voltage servo {motor_id}: {self.packet.getTxRxResult(comm)}")
        if err:
            print(f"[servo] id={motor_id} status while reading voltage: {self.packet.getRxPacketError(err)}")
        return float(voltage_raw) / 10.0

    def enable_torque(self, motor_id: int) -> None:
        comm, err = self.packet.write1ByteTxRx(motor_id, TORQUE_ENABLE_ADDR, 1)
        self._check(comm, err, f"enable torque servo {motor_id}")

    def release(self) -> None:
        for sid in self.ids:
            comm, err = self.packet.write1ByteTxRx(sid, TORQUE_ENABLE_ADDR, 0)
            self._check(comm, err, f"disable torque servo {sid}")
        print("[servo] torque off")

    def write(self, targets: dict[int, int], wait_s: float = 0.5, verbose: bool = True) -> None:
        targets = {sid: int(np.clip(pos, SERVO_MIN, SERVO_MAX)) for sid, pos in targets.items()}
        for sid, pos in targets.items():
            comm, err = self.packet.WritePosEx(sid, pos, self.cfg.speed, self.cfg.acceleration)
            self._check(comm, err, f"write servo {sid} pos={pos}")
        if wait_s:
            time.sleep(wait_s)
        if verbose:
            print(f"[servo] target={targets} readback={self.read()}")

    def _check(self, comm: int, err: int, action: str) -> None:
        if comm != self.comm_success:
            raise RuntimeError(f"{action}: {self.packet.getTxRxResult(comm)}")
        if err:
            raise RuntimeError(f"{action}: {self.packet.getRxPacketError(err)}")

    def center(self, wait_s: float = 1.0) -> None:
        self.write(
            {
                self.cfg.yaw_id: self.cfg.yaw_center,
                self.cfg.pitch_id: self.cfg.pitch_center,
            },
            wait_s=wait_s,
        )

    def center_axis(self, axis: str, wait_s: float = 1.0) -> None:
        if axis == "yaw":
            self.write({self.cfg.yaw_id: self.cfg.yaw_center}, wait_s=wait_s)
        elif axis == "pitch":
            self.write({self.cfg.pitch_id: self.cfg.pitch_center}, wait_s=wait_s)
        else:
            self.center(wait_s=wait_s)

    def monitor(self, seconds: float, period: float = 0.2) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            print(f"[servo] monitor readback={self.read()}")
            time.sleep(period)

    def move_norm(self, yaw: float, pitch: float) -> dict[int, int]:
        yaw = float(np.clip(yaw, -self.cfg.yaw_limit, self.cfg.yaw_limit))
        pitch = float(np.clip(pitch, -self.cfg.pitch_limit, self.cfg.pitch_limit))
        targets = {
            self.cfg.yaw_id: self.cfg.axis_target("yaw", yaw),
            self.cfg.pitch_id: self.cfg.axis_target("pitch", pitch),
        }
        self.write(targets, wait_s=0.0, verbose=False)
        return targets


def qmul(a, b):
    w1, x1, y1, z1 = a[3], a[0], a[1], a[2]
    w2, x2, y2, z2 = b[3], b[0], b[1], b[2]
    return np.array(
        [
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ],
        dtype=float,
    )


def qconj(q):
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=float)


def qyaw_pitch_roll(q):
    x, y, z, w = q
    yaw = math.degrees(math.atan2(2 * (x * z + w * y), 1 - 2 * (y * y + z * z)))
    pitch = math.degrees(math.asin(float(np.clip(-2 * (y * z - w * x), -1, 1))))
    roll = math.degrees(math.atan2(2 * (x * y + w * z), 1 - 2 * (x * x + z * z)))
    return yaw, pitch, roll


def spine_quat(frame):
    body = getattr(frame, "body", None)
    if body is None or not getattr(body, "active", False):
        return None
    joints = getattr(body, "joints", None)
    if joints is None or joints.shape[0] <= 3:
        return None
    return joints[3, 3:7]


class HeadMapper:
    def __init__(self, cfg: Config, use_body: bool, dead_zone_deg: float):
        self.cfg = cfg
        self.use_body = use_body
        self.dead_zone_deg = dead_zone_deg
        self.offset = np.array([0.0, 0.0, 0.0, 1.0])

    def calibrate(self, q_head, q_spine):
        self.offset = self._relative(q_head, q_spine)
        print("[pico] calibrated")

    def target(self, q_head, q_spine):
        q_rel = qmul(self._relative(q_head, q_spine), qconj(self.offset))
        yaw, pitch, roll = qyaw_pitch_roll(q_rel)
        if self.cfg.invert_yaw:
            yaw = -yaw
        if self.cfg.invert_pitch:
            pitch = -pitch
        if abs(yaw) < self.dead_zone_deg:
            yaw = 0.0
        if abs(pitch) < self.dead_zone_deg:
            pitch = 0.0
        return yaw / self.cfg.yaw_range_deg, pitch / self.cfg.pitch_range_deg, (yaw, pitch, roll)

    def _relative(self, q_head, q_spine):
        if self.use_body and q_spine is not None:
            return qmul(qconj(q_spine), q_head)
        return q_head


class Smooth:
    def __init__(self, alpha: float):
        self.alpha = alpha
        self.yaw = 0.0
        self.pitch = 0.0

    def reset(self):
        self.yaw = 0.0
        self.pitch = 0.0

    def update(self, yaw: float, pitch: float):
        self.yaw += self.alpha * (yaw - self.yaw)
        self.pitch += self.alpha * (pitch - self.pitch)
        return self.yaw, self.pitch


class Camera:
    def __init__(self, enabled: bool):
        self.pipeline = None
        if not enabled:
            return
        try:
            import pyrealsense2 as rs
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing pyrealsense2. Install optional dependency: "
                "pip install 'openneck[pico]'"
            ) from exc

        last = None
        for width, height, fps in [(1280, 720, 30), (640, 480, 30), (424, 240, 30)]:
            pipe = rs.pipeline()
            cfg = rs.config()
            cfg.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
            try:
                pipe.start(cfg)
            except Exception as exc:
                last = exc
                continue
            self.pipeline = pipe
            print(f"[camera] RGB {width}x{height}@{fps}")
            return
        raise RuntimeError(f"RealSense failed: {last}")

    def read(self):
        if self.pipeline is None:
            return None
        frames = self.pipeline.wait_for_frames(timeout_ms=250)
        color = frames.get_color_frame()
        return np.asanyarray(color.get_data()) if color else None

    def close(self):
        pipeline = self.pipeline
        self.pipeline = None
        if pipeline is not None:
            pipeline.stop()


class VideoThread:
    def __init__(self, camera: Camera, pico):
        self.camera = camera
        self.pico = pico
        self.stop = threading.Event()
        self.frames = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if self.camera.pipeline is not None:
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.thread.is_alive():
            print("[camera] video thread did not stop within timeout")

    def _run(self):
        while not self.stop.is_set():
            try:
                frame = self.camera.read()
                if frame is not None:
                    self.pico.push_video_frame(frame)
                    self.frames += 1
            except Exception as exc:
                print(f"[camera] {exc}")
                self.stop.wait(1.0)


def cmd_ports(_args) -> None:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    for port in ports:
        print(f"{port.device}\t{port.description}")


def cmd_config(args) -> None:
    cfg = with_overrides(args)
    print(json.dumps(asdict(cfg), indent=2))


def cmd_voltage(args) -> None:
    cfg = with_overrides(args)
    with Gimbal(cfg, enable_torque_on_connect=False) as gimbal:
        for sid in gimbal.ids:
            print(f"[servo] id={sid} voltage={gimbal.read_voltage(sid):.1f}V position={gimbal.read_one(sid)}")


def cmd_calibrate(args) -> None:
    cfg = with_overrides(args)
    with Gimbal(cfg, enable_torque_on_connect=False) as gimbal:
        gimbal.release()
        print("\n[1/3] Move the camera to physical forward center.")
        input("Press Enter when aligned...")
        pos = gimbal.read()
        cfg.yaw_center = int(pos[cfg.yaw_id])
        cfg.pitch_center = int(pos[cfg.pitch_id])

        cfg.yaw_min, cfg.yaw_max = record_axis_limits(gimbal, cfg.yaw_id, "yaw")
        cfg.pitch_min, cfg.pitch_max = record_axis_limits(gimbal, cfg.pitch_id, "pitch")

        validate_axis("yaw", cfg.yaw_min, cfg.yaw_center, cfg.yaw_max)
        validate_axis("pitch", cfg.pitch_min, cfg.pitch_center, cfg.pitch_max)

        save_config(cfg, Path(args.config))
        print("[calibrate] done")
        print(json.dumps(asdict(cfg), indent=2))


def record_axis_limits(gimbal: Gimbal, motor_id: int, name: str) -> tuple[int, int]:
    print(f"\nMove ONLY the {name} axis through its full safe range.")
    print("Do not force the mechanism. Press Enter when finished.")
    print("Sampling position while you move...")

    samples: list[int] = []
    rejected = 0
    last_display = 0.0
    while True:
        try:
            pos = gimbal.read_one(motor_id)
        except RuntimeError:
            rejected += 1
            pos = None
        if pos is not None:
            if samples and abs(pos - samples[-1]) > CALIBRATION_MAX_STEP_JUMP:
                rejected += 1
            else:
                samples.append(pos)
        if sys.stdin in select_ready():
            sys.stdin.readline()
            break
        now = time.time()
        if samples and now - last_display > CALIBRATION_DISPLAY_PERIOD_S:
            print(
                f"  {name}: current={samples[-1]} min={min(samples)} "
                f"max={max(samples)} rejected={rejected}",
                end="\r",
                flush=True,
            )
            last_display = now
        time.sleep(CALIBRATION_SAMPLE_PERIOD_S)
    print()

    if not samples:
        raise RuntimeError(f"No valid {name} samples captured.")
    low, high = min(samples), max(samples)
    print(f"[calibrate] {name}_min={low} {name}_max={high} rejected={rejected}")
    return int(low), int(high)


def validate_axis(name: str, low: int, center: int, high: int) -> None:
    if not low < center < high:
        raise RuntimeError(
            f"Invalid {name} calibration: min={low}, center={center}, max={high}. "
            "Center must be between min and max."
        )
    if high - low < 100:
        raise RuntimeError(
            f"Invalid {name} calibration: range too small ({high - low} steps). "
            "Move the axis through a wider safe range."
        )


def cmd_center(args) -> None:
    cfg = with_overrides(args)
    with Gimbal(cfg) as gimbal:
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            gimbal.center_axis(args.axis, wait_s=0.5)
            print("[center] press q + Enter to stop")
            deadline = time.time() + args.hold_s
            while time.time() < deadline:
                if sys.stdin in select_ready() and sys.stdin.readline().strip().lower() == "q":
                    break
                print(f"[servo] monitor readback={gimbal.read()}")
                time.sleep(0.2)
        finally:
            signal.signal(signal.SIGINT, old_handler)


def cmd_test(args) -> None:
    cfg = with_overrides(args)
    with Gimbal(cfg) as gimbal:
        axis_id = cfg.yaw_id if args.axis == "yaw" else cfg.pitch_id
        center = cfg.yaw_center if args.axis == "yaw" else cfg.pitch_center
        low = cfg.yaw_min if args.axis == "yaw" else cfg.pitch_min
        high = cfg.yaw_max if args.axis == "yaw" else cfg.pitch_max
        step = args.step
        print(f"[test] axis={args.axis} id={axis_id} center={center} min={low} max={high} step={step}")
        for target in [center, center + step, center - step, center]:
            gimbal.write({axis_id: int(np.clip(target, low, high))}, wait_s=1.0)


def cmd_run(args) -> None:
    try:
        from pico_bridge import PicoBridge
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing pico_bridge. Install optional dependency: "
            "pip install 'openneck[pico]'"
        ) from exc

    cfg = with_overrides(args)
    camera = Camera(enabled=not args.no_camera)
    video = None
    pico = None
    gimbal = None
    mapper = HeadMapper(cfg, use_body=not args.no_body, dead_zone_deg=args.dead_zone)
    smooth = Smooth(alpha=args.smoothing)

    try:
        gimbal = Gimbal(cfg).__enter__()
        pico = PicoBridge(**({"video": "frames"} if camera.pipeline else {})).__enter__()

        gimbal.center(wait_s=1.0)
        video = VideoThread(camera, pico)
        video.start()

        print("[run] look forward; terminal commands: c + Enter recalibrates, q + Enter quits")
        calibrated = False
        frames = 0
        start = time.time()
        last_status = 0.0

        while True:
            if sys.stdin in select_ready():
                cmd = sys.stdin.readline().strip().lower()
                if cmd == "q":
                    break
                if cmd == "c":
                    calibrated = False
                    smooth.reset()
                    print("[run] recalibrate requested")

            try:
                frame = pico.wait_frame(timeout=0.1)
            except TimeoutError:
                continue

            q_head = np.asarray(frame.head.rotation, dtype=float)
            q_spine = spine_quat(frame)
            if not calibrated:
                mapper.calibrate(q_head, q_spine)
                calibrated = True
                continue

            yaw, pitch, angles = mapper.target(q_head, q_spine)
            yaw, pitch = smooth.update(yaw, pitch)
            targets = {
                cfg.yaw_id: cfg.axis_target("yaw", yaw),
                cfg.pitch_id: cfg.axis_target("pitch", pitch),
            }
            if not args.dry_run:
                targets = gimbal.move_norm(yaw, pitch)
            frames += 1

            now = time.time()
            if now - last_status > args.status_s:
                fps = frames / max(now - start, 1e-6)
                print(
                    f"[run] fps={fps:.1f} yaw={angles[0]:+.1f} pitch={angles[1]:+.1f} "
                    f"cmd=({yaw:+.3f},{pitch:+.3f}) target={targets} video={video.frames if video else 0}"
                )
                last_status = now
    except KeyboardInterrupt:
        print("\n[run] interrupted")
    finally:
        cleanup_errors: list[str] = []
        for name, resource in (
            ("video thread", video),
            ("pico bridge", pico),
            ("camera", camera),
        ):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as exc:
                cleanup_errors.append(f"{name}: {exc}")
        for message in cleanup_errors:
            print(f"[cleanup] warning: {message}")
        # Leave servo torque and the serial bus untouched on run exit.


def select_ready():
    import select

    ready, _, _ = select.select([sys.stdin], [], [], 0.0)
    return ready


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--port", default=None)
    parser.add_argument("--baudrate", type=int, default=None)
    parser.add_argument("--servo-type", choices=["sts"], default=None)
    parser.add_argument("--yaw-id", type=int, default=None)
    parser.add_argument("--pitch-id", type=int, default=None)
    parser.add_argument("--yaw-center", type=int, default=None)
    parser.add_argument("--pitch-center", type=int, default=None)
    parser.add_argument("--yaw-min", type=int, default=None)
    parser.add_argument("--yaw-max", type=int, default=None)
    parser.add_argument("--pitch-min", type=int, default=None)
    parser.add_argument("--pitch-max", type=int, default=None)
    parser.add_argument("--yaw-limit", type=float, default=None)
    parser.add_argument("--pitch-limit", type=float, default=None)
    parser.add_argument("--invert-yaw", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--invert-pitch", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--speed", type=int, default=None)
    parser.add_argument("--acceleration", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple active vision driver")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ports", help="List serial ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("config", help="Show loaded config")
    add_common(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("voltage", help="Read servo voltage and position")
    add_common(p)
    p.set_defaults(func=cmd_voltage)

    p = sub.add_parser("calibrate", help="Save current physical forward pose as center")
    add_common(p)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("center", help="Move to saved center")
    add_common(p)
    p.add_argument("--axis", choices=["both", "yaw", "pitch"], default="both")
    p.add_argument("--hold-s", type=float, default=2.0)
    p.set_defaults(func=cmd_center)

    p = sub.add_parser("test", help="Move one axis by a small step")
    add_common(p)
    p.add_argument("axis", choices=["yaw", "pitch"])
    p.add_argument("--step", type=int, default=60)
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("run", help="Run PicoBridge head tracking")
    add_common(p)
    p.add_argument("--no-camera", action="store_true")
    p.add_argument("--no-body", action="store_true")
    p.add_argument("--dead-zone", type=float, default=0.5)
    p.add_argument("--smoothing", type=float, default=0.35)
    p.add_argument("--status-s", type=float, default=0.5)
    p.add_argument("--dry-run", action="store_true", help="Read PicoBridge and print targets without moving servos")
    p.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

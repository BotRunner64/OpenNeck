1. 所有配件装配好
2. 只连接yaw电机，设置id为1
python tools/change_servo_id.py --port /dev/ttyACM0 --new-id 1
3. 只连接pitch电机，设置id为2
python tools/change_servo_id.py --port /dev/ttyACM0 --new-id 2
4. 同时连接yaw和pitch电机，将yaw电机和pitch电机摆放到中位，设置物理中位
python tools/calibrate_servo_middle.py --port /dev/ttyACM0 --ids 1 2
5. 扫描id和电压，确保正常
python tools/scan_servos.py --port /dev/ttyACM0
6. 测量逻辑中位和极值，按照脚本的指示先后移动到电机的逻辑中位，极大值和极小值
python simple_active_vision.py calibrate --port /dev/ttyACM0
7. 运行脚本，戴好pico, 校准全身动捕并进入pico-bridge
python simple_active_vision.py center --speed 0 --acceleration 0
import RPi.GPIO as GPIO
import time

# 定义两个灯使用的引脚编号（BCM 编码）
LIGHT_A = 14  # 对应物理 8 号针脚
LIGHT_B = 15  # 对应物理 10 号针脚
LIGHT_C = 18  # 对应物理 10 号针脚

# 设置引脚编码模式为 BCM
GPIO.setmode(GPIO.BCM)



print("程序已启动！当前模式：A灯爆闪5秒 -> B灯爆闪5秒 -> 休息5秒 -> 循环...")
print("提示：按 Ctrl + C 可以安全退出程序。")

try:
    # 显式声明两个引脚都为输出模式
    GPIO.setup(LIGHT_A, GPIO.OUT)



    GPIO.output(LIGHT_A, GPIO.HIGH)  # 灯 A 亮
except KeyboardInterrupt:
    print("\n用户终止了程序。")

finally:
    # 无论如何，退出时清理 GPIO 资源，彻底切断引脚供电
    GPIO.cleanup()
    print("GPIO 资源已安全清理，引脚已断电。")
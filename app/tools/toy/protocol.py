"""从用户小程序中提取的 Master Remote Vibrator 分支。"""
import math

NAME = 'Master Remote Vibrator'
SERVICE = '0000ffe0-0000-1000-8000-00805f9b34fb'
WRITE_UUID = '0000ffe2-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'
STOP = bytes.fromhex('55 03 00 00 00 00')
BATTERY = bytes.fromhex('55 00')
FUNCTION_STATUS = bytes.fromhex('55 0b')


def intensity(channel1, channel2, channel3):
    values = (channel1, channel2, channel3)
    for value in values:
        if type(value) is not int or not (value == 0 or 15 <= value <= 100):
            raise ValueError('各通道强度必须为0（关闭）或15–100的整数。')
    mapped3 = 0 if channel3 == 0 else math.floor(50 * ((channel3 - 15) / 85) + 34 + 0.5)
    return bytes((0x55, 0x03, 7, channel2, mapped3, channel1))

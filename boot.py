import board
import digitalio
import storage
import usb_hid
import usb_cdc
import time

# 右上のキー C0R0（行0: GP9, 列0: GP5）のみを初期化
row0 = digitalio.DigitalInOut(board.GP9)
row0.direction = digitalio.Direction.OUTPUT
row0.value = True

col0 = digitalio.DigitalInOut(board.GP5)
col0.direction = digitalio.Direction.INPUT
col0.pull = digitalio.Pull.DOWN

# 電位安定待ち
time.sleep(0.05)

# 押されていれば ROW0のHighが伝わり True になる
is_key_pressed = col0.value

# 使用したピンを解放（code.py の keypad で再利用するために必須）
row0.deinit()
col0.deinit()

# モードの切り替え
if is_key_pressed:
    storage.remount("/", True)   # 開発モード（PCから書き込み可）
    print("【開発モード】")
else:
    storage.remount("/", False)  # 通常モード（PCからは読み取り専用）
    print("【通常モード】")

# USBデバイス設定
usb_hid.disable()
usb_hid.enable((usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE))
usb_cdc.enable(console=True, data=True)

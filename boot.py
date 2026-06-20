import usb_hid
import supervisor

# オートリロードを無効化
supervisor.disable_autoreload()

# 一旦デフォルトの自己紹介をリセット
usb_hid.disable()

# キーボードだけを使うとPCに宣言
usb_hid.enable(
    (usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE)
)
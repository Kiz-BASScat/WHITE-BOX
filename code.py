import time
import board
import keypad
import usb_hid
import analogio
import digitalio
import math
import json
import usb_cdc
import neopixel_write

##############################################
#LED設定
##############################################
# GP16を通常のデジタル出力として初期化
led_pin = digitalio.DigitalInOut(board.GP16)
led_pin.direction = digitalio.Direction.OUTPUT

#1:Normal, 2:Error, 3:Setting
LED_DATA = bytearray(3)
def led_on(mode):
    brightness = 0.1
    if mode == 1:r, g, b = 200, 0, 255
    elif mode == 2: r, g, b = 255, 0, 0
    elif mode == 3: r, g, b = 0, 0, 255
    else: r, g, b = 0, 0, 0 
    
    # 輝度を適用して整数に変換
    #RP2040-ZeroのGRB順の仕様に合わせて送信
    LED_DATA[0] = int(g * brightness)
    LED_DATA[1] = int(r * brightness)
    LED_DATA[2] = int(b * brightness)
    
    neopixel_write.neopixel_write(led_pin, LED_DATA)


##############################################
#ユーザ設定読み書き
##############################################
SETTING_FILE = "user_setting.json"

def load_settings():
    try:
        with open(SETTING_FILE, "r") as f:
            return json.load(f)
    except(OSError, ValueError):
        return None
def write_settings(data):
    try:
        with open(SETTING_FILE, "w") as f:
            f.write(data)
            return True
    except(OSError, ValueError):
        return False
    
##############################################
#ハードウェア設定
##############################################
class __Key:
    def __init__(self, modifier, keycodes: tuple):
        self.report = bytearray(8)
        self.report[0] = int(modifier)
        if len(keycodes) < 7: 
            for i, code in enumerate(keycodes):
                self.report[2 + i] = int(code)
        print(self.report)
class Mouse:
    def __init__(self):
        self.__device = usb_hid.devices[1]
        self.__kbd = usb_hid.devices[0]
        self.__x = analogio.AnalogIn(board.GP29)
        self.__y = analogio.AnalogIn(board.GP28)
        self.__with_key_report = bytearray(8)
        self.__with_key_report[2] = 0x00 #スペース;0x2C
        self.__with_button_report = bytearray(4)
        self.__with_button_report[0] = 0x00  #左クリック;0x01
        self.__deadzone_sq = 400 ** 2
        self.__max = 65536
        self.__min = 0
        self.__cnt = int((self.__max - self.__min) / 2) 
        self.__speed = 2
        
        self.config_update()

        #操作中フラグ
        self.is_moving = False

        #変位の正規化
        self.__shift_bit = 16
        self.__table_size = 1024
        self.__inv_sqrt_table = tuple(        #2進数でのビットシフトなので、2^nの割り算に相当
            int((1.0 / math.sqrt(max(i << self.__shift_bit, 1))) * self.__max)
            for i in range(self.__table_size)
        )

        #デッドゾーン内経過時間
        self.__stop_delay = 0.10
        self.__stop_timer = None
        #デッドゾーン内で送る変位
        self.__last_dx = 0
        self.__last_dy = 0

    def config_update(self):
        settings = load_settings()
        if settings and "mouse_setting" in settings:
            print("JSON設定をマウスに反映します...")

            try:
                temp_key_code = settings["mouse_setting"]["with_key"]
                temp_button_code = settings["mouse_setting"]["with_button"]
                temp_deadzone = settings["mouse_setting"]["deadzone"]
                temp_speed = settings["mouse_setting"]["speed"]

                self.__with_key_report[2] = temp_key_code
                self.__with_button_report[0] = temp_button_code
                self.__deadzone_sq = temp_deadzone ** 2
                self.__speed = int(temp_speed * 10.24)
                print("成功")
                led_on(1)

            except (KeyError, ValueError) as e:
                # JSON内のキー名が足りない、または数値変換に失敗した場合
                print("JSONデータ(mouse_setting)のパースに失敗しました: ", e)
                led_on(2)

        else:
            print("設定ファイルが見つからないか破損しています")
            led_on(2)

        return


    def get_velocity(self):
        dx = self.__x.value - self.__cnt
        dy = self.__y.value - self.__cnt
        dist_sq = dx ** 2 +  dy ** 2
        if self.__deadzone_sq > dist_sq:
            return 0, 0,

        idx = (dist_sq >> self.__shift_bit)
        if idx >= self.__table_size:
            idx = self.__table_size - 1

        inv_dist = self.__inv_sqrt_table[idx]

        dx_norm = (dx * inv_dist * self.__speed) >> 24
        dy_norm = -(dy * inv_dist * self.__speed) >> 24

        return dx_norm, dy_norm

    def send_release(self):
        self.__device.send_report(b'\x00' * 4)
        self.__kbd.send_report(b'\x00' * 8)

    def send_moving(self, dx, dy):
        self.__with_button_report[1] = max(-127, min(127, dx)) & 0xFF
        self.__with_button_report[2] = max(-127, min(127, dy)) & 0xFF
        self.__device.send_report(self.__with_button_report)

    def send_key(self):
        self.__kbd.send_report(self.__with_key_report)

    def update(self):
        dx, dy = self.get_velocity()
        #DEADZONE内
        if dx == 0 and dy == 0:
            current_time = time.monotonic()
            #外から内に移動
            if self.is_moving:
                #内に入ってきたらタイマースタート
                if self.__stop_timer is None:
                    self.__stop_timer = current_time
                
                #内側で一定秒経過
                if current_time - self.__stop_timer >= self.__stop_delay:
                    #リリース判定と処理, 操作中フラグを折る
                    self.send_release()
                    self.is_moving = False
                    self.__stop_timer = None
                    self.__last_dx = 0
                    self.__last_dy = 0

                #内側で一定秒以内
                else:
                    #直前の速度を減速して送信
                    self.__last_dx = int(self.__last_dx * 0.7)
                    self.__last_dy = int(self.__last_dy * 0.7)
                    self.send_moving(self.__last_dx, self.__last_dy)

        #DEADZONE外
        else:
            #現在の速度を送信, 操作中フラグを立てる
            if not self.is_moving: self.send_key()
            self.send_moving(dx, dy)
            self.__stop_timer = None
            self.is_moving = True


class Kbd:
    def __init__(self):
        self.__device = usb_hid.devices[0]
        self.__keys = (
            __Key(0x00, (0x00,)),#C0R0
            __Key(0x00, (0x00,)),#C1R0
            __Key(0x00, (0x00,)),#C2R0
            __Key(0x00, (0x00,)),#C3R0
            __Key(0x00, (0x00,)),#C0R1
            __Key(0x00, (0x00,)),#C1R1
            __Key(0x00, (0x00,)),#C2R1
            __Key(0x00, (0x00,)),#C3R1
            __Key(0x00, (0x00,)),#C0R2
            __Key(0x00, (0x00,)),#C1R2
            __Key(0x00, (0x00,)),#C2R2
            __Key(0x00, (0x00,)) #C3R2
        )
        self.is_holding = False
        self.current_key_number = None
        self.event = keypad.KeyMatrix(
            row_pins=(board.GP9, board.GP10, board.GP11),
            column_pins=(board.GP8, board.GP7, board.GP6, board.GP5), 
            columns_to_anodes=False,
            interval=0.02
        ).events
        self.config_update()

    def config_update(self):
        settings = load_settings()
        if settings and "key_settings" in settings:
            print("JSON設定をキーに反映します...")
            temp_keys = []
            keys_order = [
                "key_C0R0", "key_C1R0", "key_C2R0", "key_C3R0",
                "key_C0R1", "key_C1R1", "key_C2R1", "key_C3R1",
                "key_C0R2", "key_C1R2", "key_C2R2", "key_C3R2"
            ]
            try:
                for key_name in keys_order:
                        print(settings["key_settings"][key_name])
                        key_data = settings["key_settings"][key_name]
                        temp_keys.append(__Key(key_data["mod"], tuple(key_data["codes"])))

                self.__keys = tuple(temp_keys)
                print("成功")
                
                led_on(1)

            except (KeyError, ValueError) as e:
                # JSON内のキー名が足りない、または数値変換に失敗した場合
                print("JSONデータ(key_settings)のパースに失敗しました: ", e)
                led_on(2)

        else:
            print("設定ファイルが見つからないか破損しています")
            led_on(2)

        return

    def send_report(self):
        #self.current_key_number = key_number
        if self.current_key_number is None:
            self.__device.send_report(b'\x00' * 8)
        else:
            print(self.__keys[self.current_key_number].report)
            self.__device.send_report(self.__keys[self.current_key_number].report)

    def update(self):
        event = kbd.event.get()
        if event:      
            if event.pressed:
                self.current_key_number = event.key_number
                self.is_holding = True
            elif event.released:
                self.current_key_number = None
                self.is_holding = False

            self.send_report()

    def reset(self):
        self.current_key_number = None
        self.is_holding = False
        self.send_report()

serial = usb_cdc.data if usb_cdc.data is not None else usb_cdc.console
if serial:
    serial.timeout = 0.2

CMD_GET = "GET_SETTING"
CMD_SAVE = "SAVE_SETTING"

tStart = time.monotonic()
s_time = time.monotonic()
mouse = Mouse()
kbd = Kbd()
led_on(1)
while True:
    #PCからの命令チェック
    if serial and serial.in_waiting > 0:

        try:
            row_line = serial.readline()
            if row_line:
                line = row_line.decode("utf-8").strip()
                
                if CMD_GET in line:
                    led_on(3)
                    serial.reset_output_buffer()
                    current_settings = load_settings()
                    if current_settings:
                        serial.write((json.dumps(current_settings) + "\n").encode("utf-8"))
                    else:
                        serial.write(b"ERROR:LOAD_FAILED\n")
                    led_on(1)
                elif line.startswith(CMD_SAVE):
                    led_on(3)
                    json_str = line[len(CMD_SAVE):]
                    new_settings = json.loads(json_str)
                    if write_settings(json_str):
                        serial.write(b"SUCCESS\n")
                        mouse.config_update()
                        kbd.config_update()
                    else:
                        serial.write(b"ERROR:WRITE_FAILED\n")
                    led_on(1)
        except:
            if serial: serial.write(b"ERROR:EXCEPTION\n")
            led_on(2)

    #入力処理
    if kbd.is_holding: kbd.update()
    elif mouse.is_moving: mouse.update()
    else:
        kbd.update()
        if not kbd.is_holding: mouse.update()

    time.sleep(0.01)

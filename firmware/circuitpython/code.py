"""Same CircuitPython firmware for Pico W and ESP32 boards with native wifi."""
import os
import time
import json
import board
import digitalio
import socketpool
import wifi
from button import Button

SSID = os.getenv('BUTTON_WIFI_SSID', 'iMac-TDM')
PASSWORD = os.getenv('BUTTON_WIFI_PASSWORD')
HOST = os.getenv('CONTROLLER_HOST', '192.168.77.1')
PORT = int(os.getenv('CONTROLLER_PORT', '8080'))
TOKEN = os.getenv('CONTROLLER_TOKEN')
PIN = os.getenv('BUTTON_PIN', 'GP15')
if not PASSWORD or not TOKEN or len(TOKEN) < 32:
    raise ValueError('Configure settings.toml first')
switch = digitalio.DigitalInOut(getattr(board, PIN))
switch.switch_to_input(pull=digitalio.Pull.UP)
led = None
led_pin = os.getenv('LED_PIN', '')
if led_pin:
    led = digitalio.DigitalInOut(getattr(board, led_pin))
    led.switch_to_output(value=False)
pool = socketpool.SocketPool(wifi.radio)
button = Button()


def request(method, path, data=None):
    body = json.dumps(data) if data is not None else ''
    message = ('%s %s HTTP/1.0\r\nHost: %s\r\nAuthorization: Bearer %s\r\n'
               'Content-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s'
               % (method, path, HOST, TOKEN, len(body.encode()), body)).encode()
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect((HOST, PORT))
        sent = 0
        while sent < len(message):
            n = sock.send(message[sent:])
            if n <= 0:
                raise OSError('Connection closed')
            sent += n
        result = bytearray()
        buf = bytearray(256)
        while True:
            n = sock.recv_into(buf)
            if n == 0:
                break
            result.extend(buf[:n])
            if len(result) > 2048:
                raise ValueError('Response too large')
        head, payload = bytes(result).split(b'\r\n\r\n', 1)
        if head.split(b'\r\n', 1)[0].split()[1] != b'200':
            raise OSError('Controller rejected request')
        return json.loads(payload.decode())
    finally:
        sock.close()


last_connect = -10
connected_before = False
while True:
    now = time.monotonic()
    if not wifi.radio.connected:
        connected_before = False
        button.reset()
        if led:
            led.value = False
        # Do not connect while held; offline presses must never become commands.
        if switch.value and now-last_connect > 10:
            last_connect = now
            try:
                wifi.radio.connect(SSID, PASSWORD, timeout=5)
            except (OSError, ConnectionError) as error:
                print('WLAN unavailable:', error)
        time.sleep(.02)
        continue
    if not connected_before:
        button.reset()
        connected_before = True
    event = button.update(not switch.value, now)
    if event:
        try:
            ticket = request('GET', '/ticket')['ticket']
            result = request('POST', '/event', {'ticket': ticket, 'gesture': event})
            print('Controller:', result['action'])
            if led:
                led.value = result['action'] not in ('unavailable', 'none')
        except (OSError, ValueError, KeyError) as error:
            print('Event discarded:', error)
            if led:
                led.value = False
        # Network calls can block: require release rather than reinterpret a hold.
        button.reset()
    time.sleep(.01)

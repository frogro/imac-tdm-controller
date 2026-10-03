#!/usr/bin/env python3
"""Guided CircuitPython button installer; runs on Linux, not on the Pi exclusively."""
import argparse
import ast
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'pico-w': dict(label='Raspberry Pi Pico W', pin='GP15', wire='GP15 (physischer Pin 20) ↔ Taster ↔ GND (Pin 18)',
                   board_id='raspberry_pi_pico_w', transport='uf2'),
    'esp32': dict(label='ESP32 DevKit v1 / ESP32-WROOM-32 (4 MB)', pin='D4',
                  wire='GPIO4 / IO4 ↔ Taster ↔ GND (Beschriftung auf der Platine)',
                  board_id='doit_esp32_devkit_v1', transport='serial'),
    'esp32-devkitc': dict(label='ESP32-DevKitC V4 / ESP32-WROOM-32E (4 MB)', pin='IO4',
                  wire='GPIO4 / IO4 (J3 Pin 13) ↔ Taster ↔ GND (J3 Pin 1)',
                  board_id='espressif_esp32_devkitc_v4_wroom_32e', transport='serial'),
    'tinypico': dict(label='Unexpected Maker TinyPICO V3 USB-C', pin='IO25',
                  wire='GPIO25 / 25 ↔ Taster ↔ GND (Beschriftung auf der Platine)',
                  board_id='unexpectedmaker_tinypico', transport='serial'),
}


def settings_text(profile, ssid, password, host, token):
    if not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password) <= 63:
        raise ValueError('SSID or WLAN password length is invalid')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValueError('Controller token must contain 32–128 letters, digits, _ or -')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
        raise ValueError('Invalid controller address')
    data = dict(BUTTON_WIFI_SSID=ssid, BUTTON_WIFI_PASSWORD=password,
                CONTROLLER_HOST=host, CONTROLLER_PORT='8080', CONTROLLER_TOKEN=token,
                BUTTON_PIN=profile['pin'], LED_PIN='LED' if profile['transport'] == 'uf2' else '')
    return ''.join(f'{k} = {json.dumps(v, ensure_ascii=True)}\n' for k, v in data.items())


def parse_settings(path):
    # The generated file contains only string assignments, compatible with TOML.
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        value = ast.literal_eval(value.strip())
        if not isinstance(value, str):
            raise ValueError('Expected string settings')
        result[key.strip()] = value
    return result


def firmware_data(key):
    info = json.loads((ROOT/'firmware/releases.json').read_text())[key]
    print('Lade CircuitPython', info['version'], 'für', PROFILES[key]['label'])
    with urllib.request.urlopen(info['url'], timeout=60) as response:
        data = response.read(info['size']+1)
    if len(data) != info['size'] or hashlib.sha256(data).hexdigest() != info['sha256']:
        raise ValueError('Firmware-Prüfsumme stimmt nicht; nichts geflasht')
    return data


def validate_mount(path, expected):
    path = path.resolve()
    if not path.is_dir() or not os.path.ismount(path):
        raise ValueError('Bitte das tatsächlich eingehängte Board-Laufwerk auswählen')
    if expected == 'boot':
        text = (path/'INFO_UF2.TXT').read_text()
        if 'RPI-RP2' not in text and 'Raspberry Pi RP2' not in text:
            raise ValueError('Kein RP2040-BOOTSEL-Laufwerk')
    else:
        text = (path/'boot_out.txt').read_text()
        if 'CircuitPython' not in text or 'Board ID:raspberry_pi_pico_w' not in text:
            raise ValueError('CIRCUITPY gehört nicht zum ausgewählten Pico W')
    return path


def confirmed(message):
    print(message)
    if input('Zum Fortfahren INSTALLIEREN eingeben: ').strip() != 'INSTALLIEREN':
        raise ValueError('Abgebrochen; Installation nicht freigegeben')


def mount_prompt(message, expected):
    print(message)
    print('Beispiel: /run/media/DEINNAME/RPI-RP2 oder /media/DEINNAME/CIRCUITPY')
    return validate_mount(Path(input('Einhängepfad: ').strip()).expanduser(), expected)


def install_pico(profile, files, fresh):
    if fresh:
        data = firmware_data('pico-w')
        # RP2040 UF2 family; protect against accidentally using another image.
        if struct.unpack_from('<I', data, 0)[0] != 0x0A324655 or struct.unpack_from('<I', data, 28)[0] != 0xE48BFF56:
            raise ValueError('Firmware ist kein RP2040-UF2')
        mount = mount_prompt('Pico W mit gehaltener BOOTSEL-Taste an USB anschließen.', 'boot')
        confirmed(f'CircuitPython auf {mount} installieren. Vorhandene Board-Daten vorher sichern.')
        with (mount/'firmware.uf2').open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        print('Board startet neu. Auf das CIRCUITPY-Laufwerk warten.')
    mount = mount_prompt('Pico W mit CircuitPython anschließen.', 'circuitpy')
    confirmed(f'Tasterdateien und settings.toml auf {mount} installieren/ersetzen.')
    # Copy code last: an autoreload before then cannot act on partial configuration.
    for name, data in files.items():
        path = mount/name
        if path.is_symlink():
            raise ValueError('Symlink als Ziel nicht erlaubt: '+name)
        with path.open('wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        if path.read_bytes() != data:
            raise ValueError('Rückleseprüfung fehlgeschlagen: '+name)


class RawREPL:
    def __init__(self, port):
        import serial
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=3)
        self.port.dtr = False
        self.port.rts = False
        self.port.port = port
        self.port.open()
        # Opening the UART can reset an ESP32. The first input may only wake
        # CircuitPython's serial console, so allow boot and retry the handshake.
        try:
            time.sleep(2)
            for attempt in range(3):
                self.port.write(b'\r\x03\x03')
                time.sleep(.5)
                self.port.reset_input_buffer()
                self.port.write(b'\r\x01')
                try:
                    self.until(b'raw REPL; CTRL-B to exit\r\n>', timeout=4)
                    break
                except ValueError:
                    if attempt == 2:
                        raise
        except Exception:
            self.port.close()
            raise

    def until(self, suffix, timeout=8):
        output = bytearray()
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            output.extend(self.port.read(256))
            if output.endswith(suffix):
                return bytes(output)
            if len(output) > 65536:
                break
        raise ValueError('CircuitPython-REPL antwortet nicht. Board zurücksetzen und Port prüfen.')

    def execute(self, code):
        # Stay below UART buffers; source/error text may contain credentials: never log it.
        data = code.encode()
        for start in range(0, len(data), 128):
            self.port.write(data[start:start+128]); time.sleep(.02)
        self.port.write(b'\x04')
        output = self.until(b'\x04>')
        if not output.startswith(b'OK'):
            raise ValueError('REPL-Protokollfehler')
        stdout, stderr, tail = output[2:].split(b'\x04', 2)
        if stderr.strip():
            raise ValueError('Board konnte die Aktion nicht ausführen; keine Zugangsdaten ausgegeben')
        return stdout

    def close(self):
        self.port.write(b'\x02')
        self.port.close()


def install_esp(profile, files, fresh):
    try:
        import serial.tools.list_ports
        import esptool
    except ImportError:
        raise ValueError('ESP32 benötigt: python3 -m pip install pyserial esptool (in einer venv)') from None
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        raise ValueError('Kein serieller USB-Port gefunden')
    for i, port in enumerate(ports, 1):
        print(f'{i}: {port.device} — {port.description}')
    choice = int(input('Nummer des ESP32-USB-Ports: '))-1
    if not 0 <= choice < len(ports):
        raise ValueError('Ungültiger Port')
    port = ports[choice].device
    if fresh:
        data = firmware_data(next(k for k, v in PROFILES.items() if v is profile))
        confirmed(f'ESP32 auf {port}: gesamten Flash löschen und CircuitPython installieren. Nur {profile["label"]}!')
        print('Falls keine Verbindung entsteht: BOOT gedrückt halten und kurz EN/RESET drücken.')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'firmware.bin'; path.write_bytes(data)
            # Fixed chip type rejects ESP32-S2/S3/C3; esptool checks image chip metadata.
            base = [sys.executable, '-m', 'esptool', '--chip', 'esp32', '--port', port]
            subprocess.run(base+['erase-flash'], check=True)
            subprocess.run(base+['write-flash', '0x0', str(path)], check=True)
        input('Nach dem Neustart kurz warten, dann Enter zum Kopieren der Tasterdateien: ')
    repl = RawREPL(port)
    try:
        board_id = repl.execute('import board; print(board.board_id)').decode().strip()
        if board_id != profile['board_id']:
            raise ValueError('Installiertes CircuitPython passt nicht zum gewählten Board')
        confirmed(f'Tasterdateien und WLAN-Konfiguration auf {port} installieren/ersetzen.')
        repl.execute('import supervisor; supervisor.runtime.autoreload = False')
        for name, data in files.items():
            repl.execute(f'f=open({name!r},"wb"); f.close()')
            for start in range(0, len(data), 192):
                chunk = data[start:start+192]
                repl.execute(f'f=open({name!r},"ab"); f.write({chunk!r}); f.close()')
            # SHA256 is not universally included; compare bounded readback chunks.
            for start in range(0, len(data), 192):
                returned = repl.execute(f'import binascii; f=open({name!r},"rb"); f.seek({start}); print(binascii.hexlify(f.read(192)).decode()); f.close()')
                if returned.decode().strip() != data[start:start+192].hex():
                    raise ValueError('Rückleseprüfung fehlgeschlagen: '+name)
        repl.execute('import os; os.sync()')
    finally:
        repl.close()
    print('ESP32 jetzt mit EN/RESET neu starten, damit settings.toml neu geladen wird.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, help='Vom Pi-Installer erzeugte button-settings.toml')
    parser.add_argument('--prepare-only', type=Path, help='Dateien lokal vorbereiten, ohne ein Board zu verändern')
    args = parser.parse_args()
    print('WLAN-Taster einrichten — gleicher CircuitPython-Code für alle unterstützten Boards')
    keys = list(PROFILES)
    for n, key in enumerate(keys, 1): print(f'{n}: {PROFILES[key]["label"]}')
    index = int(input('Board auswählen [' + '/'.join(str(n) for n in range(1, len(keys)+1)) + ']: '))-1
    if not 0 <= index < len(keys): raise ValueError('Ungültige Boardauswahl')
    key = keys[index]; profile = PROFILES[key]
    if args.settings:
        settings = parse_settings(args.settings)
        ssid, password, host, token = (settings[k] for k in ('BUTTON_WIFI_SSID', 'BUTTON_WIFI_PASSWORD', 'CONTROLLER_HOST', 'CONTROLLER_TOKEN'))
    else:
        ssid = input('Pi-WLAN-Name [iMac-TDM]: ').strip() or 'iMac-TDM'
        password = getpass.getpass('Pi-WLAN-Passwort: ')
        host = input('Pi-Adresse [192.168.77.1]: ').strip() or '192.168.77.1'
        token = getpass.getpass('Controller-Token aus der Pi-Konfiguration: ').strip()
    settings = settings_text(profile, ssid, password, host, token).encode()
    files = {'settings.toml': settings, 'button.py': (ROOT/'firmware/circuitpython/button.py').read_bytes(),
             'code.py': (ROOT/'firmware/circuitpython/code.py').read_bytes()}
    if args.prepare_only:
        destination = args.prepare_only.resolve()
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, data in files.items():
            (destination/name).write_bytes(data); (destination/name).chmod(0o600)
        print('Vorbereitet (noch nicht auf einem Board installiert):', destination)
    else:
        answer = input('CircuitPython neu installieren? [j/N]: ').strip().lower()
        fresh = answer in ('j', 'ja', 'y', 'yes')
        if profile['transport'] == 'uf2': install_pico(profile, files, fresh)
        else: install_esp(profile, files, fresh)
        print('Tasterdateien geschrieben und zurückgelesen.')
    print('\nVerdrahtung für', profile['label'])
    print(profile['wire'])
    print('Normal offenen Taster verwenden. Interner Pull-up ist aktiviert; kein externer Widerstand nötig.')
    print('Taster nur zwischen GPIO und GND anschließen, nicht an 5 V oder 3,3 V.')
    if key == 'tinypico':
        print('Akku: geschützter 1S-LiPo (3,7 V) am JST-Anschluss; +/− prüfen. Laden über USB-C.')
        print('Noch kein Tiefschlaf: WLAN bleibt eingeschaltet.')
    print('Kurz: beim Loslassen. Lang: ab 3 Sekunden, nur einmal pro Druck.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, EOFError, KeyboardInterrupt, subprocess.CalledProcessError) as error:
        print('Abbruch:', error, file=sys.stderr)
        sys.exit(1)

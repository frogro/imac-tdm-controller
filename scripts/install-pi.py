#!/usr/bin/env python3
"""Install on a dedicated Raspberry Pi Zero W/Zero 2 W with Raspberry Pi OS Lite."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import uuid
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def load_button_settings(path):
    data = tomllib.loads(path.read_text())
    for key in ('BUTTON_WIFI_SSID', 'BUTTON_WIFI_PASSWORD', 'CONTROLLER_TOKEN'):
        if not isinstance(data.get(key), str):
            raise ValueError('Missing or invalid button setting: ' + key)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', data['CONTROLLER_TOKEN']):
        raise ValueError('Invalid controller token')
    if data.get('CONTROLLER_HOST') != '192.168.77.1' or str(data.get('CONTROLLER_PORT')) != '8080':
        raise ValueError('Existing button must target 192.168.77.1:8080')
    return data


def has_existing_dwc2(config):
    # Stock images include a CM5-only host overlay, which does not apply to Zero.
    section = 'all'
    for line in config.splitlines():
        line = line.split('#', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif section not in ('cm4', 'cm5', 'none') and re.match(r'dtoverlay\s*=\s*dwc2(?:,|$)', line):
            return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--ssid')
    p.add_argument('--settings', type=Path, help='Vorhandene vertrauliche Taster-Konfiguration übernehmen')
    args = p.parse_args()
    model_file = Path('/proc/device-tree/model')
    model = model_file.read_text().rstrip('\0') if model_file.exists() else ''
    if not ('Raspberry Pi Zero W' in model or 'Raspberry Pi Zero 2 W' in model):
        p.error('Run this installer on the dedicated Pi Zero W/Zero 2 W, not the iMac/build PC')
    if os.geteuid() != 0:
        p.error('Run with sudo')
    for command in ('nmcli', 'systemctl', 'modprobe'):
        if shutil.which(command) is None:
            p.error('Install required tool first: '+command)
    existing = load_button_settings(args.settings) if args.settings else None
    args.ssid = args.ssid or (existing['BUTTON_WIFI_SSID'] if existing else 'iMac-TDM')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', args.ssid):
        p.error('SSID: use 1–32 letters, digits, underscores or hyphens')
    image = args.image.resolve(strict=True)
    if not image.is_file():
        p.error('Image must be a regular file')
    meta = json.loads(image.with_suffix('.json').read_text())
    sha = hashlib.sha256()
    with image.open('rb') as f:
        for block in iter(lambda: f.read(1024**2), b''): sha.update(block)
    if sha.hexdigest() != meta['sha256'] or image.stat().st_size != meta['image_size']:
        p.error('Image checksum mismatch; use a fresh image from build-image.py')
    destination = Path('/opt/imac-tdm-controller')
    config_dir = Path('/etc/imac-tdm-controller')
    if destination.exists() or config_dir.exists():
        p.error('Already installed; stop services and preserve configuration before replacing')
    boot = Path('/boot/firmware/config.txt')
    if not boot.exists(): boot = Path('/boot/config.txt')
    old = boot.read_text()
    if has_existing_dwc2(old) or 'g_ether' in (boot.parent/'cmdline.txt').read_text():
        p.error('Existing gadget configuration found; reconcile it before installation')
    password = existing['BUTTON_WIFI_PASSWORD'] if existing else getpass.getpass('Neues Passwort für das Pi-WLAN (8–63 ASCII-Zeichen): ')
    if not 8 <= len(password) <= 63 or not re.fullmatch(r'[A-Za-z0-9_-]+', password):
        p.error('Use 8–63 letters, digits, underscores or hyphens')
    if not existing and password != getpass.getpass('WLAN-Passwort wiederholen: '):
        p.error('Passwords differ')
    token = existing['CONTROLLER_TOKEN'] if existing else secrets.token_hex(32)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        p.error('Invalid controller token')
    config_dir.mkdir(mode=0o700)
    destination.mkdir()
    shutil.copytree(ROOT/'controller', destination/'controller', ignore=shutil.ignore_patterns('__pycache__'))
    target = Path('/var/lib/imac-tdm-controller')
    target.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(image, target/'boot.img')
    (target/'boot.img').chmod(0o600)
    config = dict(image=str(target/'boot.img'), state_offset=meta['state_offset'],
                  serial=secrets.token_hex(8), token=token, listen='192.168.77.1', port=8080)
    write(config_dir/'config.json', json.dumps(config, indent=2)+'\n', 0o600)
    connection_uuid = str(uuid.uuid4())
    write(Path('/etc/NetworkManager/system-connections/imac-tdm.nmconnection'), f'''[connection]
id=imac-tdm
uuid={connection_uuid}
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100
[wifi]
mode=ap
ssid={args.ssid}
band=bg
[wifi-security]
key-mgmt=wpa-psk
psk={password}
[ipv4]
method=shared
address1=192.168.77.1/24
[ipv6]
method=disabled
''', 0o600)
    # Backup, then enable the Pi device controller on its USB data port.
    shutil.copyfile(boot, config_dir/'config.txt.before')
    write(boot, old.rstrip()+'\n\n# iMac TDM USB device\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n')
    write(Path('/etc/modules-load.d/imac-tdm.conf'), 'dwc2\nlibcomposite\n')
    write(Path('/etc/systemd/system/imac-tdm-gadget.service'), '''[Unit]
Description=iMac TDM USB boot disk and HID devices
After=local-fs.target systemd-modules-load.service
Before=imac-tdm-controller.service
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/imac-tdm-controller
ExecStart=/usr/bin/python3 -m controller.gadget start
ExecStop=/usr/bin/python3 -m controller.gadget stop
[Install]
WantedBy=multi-user.target
''')
    write(Path('/etc/systemd/system/imac-tdm-controller.service'), '''[Unit]
Description=iMac TDM WLAN button controller
Requires=imac-tdm-gadget.service NetworkManager.service
After=imac-tdm-gadget.service NetworkManager.service
[Service]
WorkingDirectory=/opt/imac-tdm-controller
ExecStartPre=/usr/bin/nmcli connection up imac-tdm
ExecStart=/usr/bin/python3 -m controller.server --config /run/imac-tdm-controller/config.json
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
''')
    settings = (ROOT/'firmware/circuitpython/settings.example.toml').read_text()
    settings = settings.replace('iMac-TDM', args.ssid).replace('REPLACE_WITH_PI_AP_PASSWORD', password).replace('REPLACE_WITH_TOKEN_FROM_PI_INSTALLER', token)
    write(config_dir/'button-settings.toml', settings, 0o600)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'imac-tdm-gadget.service', 'imac-tdm-controller.service'], check=True)
    print('Installiert. WLAN-Land mit raspi-config setzen, dann Pi neu starten.')
    print('Taster-Konfiguration: /etc/imac-tdm-controller/button-settings.toml (vertraulich).')
    print('Beim Neustart wechselt wlan0 in den AP-Modus; bestehende WLAN-Verbindungen enden.')


if __name__ == '__main__':
    main()

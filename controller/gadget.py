#!/usr/bin/env python3
"""Configure a Pi OTG composite gadget. Does not edit an attached backing image."""
import argparse
import json
from pathlib import Path
import subprocess
from controller.core import KEYBOARD_DESCRIPTOR, POWER_DESCRIPTOR

BASE = Path('/sys/kernel/config/usb_gadget/imac_tdm')


def put(path, value):
    path.write_bytes(value if isinstance(value, bytes) else str(value).encode())


def stop():
    if not BASE.exists():
        return
    put(BASE / 'UDC', '')
    for path in (BASE / 'configs/c.1').iterdir():
        if path.is_symlink():
            path.unlink()
    for name in ('hid.keyboard', 'hid.power', 'mass_storage.boot'):
        path = BASE / 'functions' / name
        if path.exists():
            path.rmdir()
    for name in ('configs/c.1/strings/0x409', 'configs/c.1', 'strings/0x409'):
        path = BASE / name
        if path.exists():
            path.rmdir()
    BASE.rmdir()


def start(config):
    image = Path(config['image']).resolve(strict=True)
    if not image.is_file():
        raise ValueError('Backing image must be a regular file, never a block device')
    subprocess.run(['modprobe', 'libcomposite'], check=True)
    controllers = sorted(Path('/sys/class/udc').iterdir())
    if len(controllers) != 1:
        raise ValueError('Expected one enabled USB device controller; configure dwc2 peripheral mode')
    if BASE.exists():
        raise ValueError('Gadget already exists; stop the service before reconfiguration')
    BASE.mkdir()
    try:
        # Linux Foundation example VID/PID, for personal prototyping only.
        put(BASE/'idVendor', '0x1d6b')
        put(BASE/'idProduct', '0x0104')
        put(BASE/'bcdDevice', '0x0100')
        put(BASE/'bcdUSB', '0x0200')
        strings = BASE/'strings/0x409'
        strings.mkdir()
        for key, value in {'serialnumber': config['serial'], 'manufacturer': 'iMac TDM project', 'product': 'iMac TDM Controller'}.items():
            put(strings/key, value)
        conf = BASE/'configs/c.1'
        conf.mkdir()
        (conf/'strings/0x409').mkdir()
        put(conf/'strings/0x409/configuration', 'Boot disk, keyboard and power key')
        put(conf/'MaxPower', '250')
        for name, protocol, subclass, length, descriptor in (
                ('hid.keyboard', 1, 1, 8, KEYBOARD_DESCRIPTOR),
                ('hid.power', 0, 0, 1, POWER_DESCRIPTOR)):
            fun = BASE/'functions'/name
            fun.mkdir()
            for key, value in {'protocol': protocol, 'subclass': subclass, 'report_length': length, 'report_desc': descriptor}.items():
                put(fun/key, value)
            (conf/name).symlink_to(fun)
        storage = BASE/'functions/mass_storage.boot'
        storage.mkdir()
        for key, value in {'stall': 1, 'lun.0/removable': 1, 'lun.0/ro': 0, 'lun.0/nofua': 0, 'lun.0/file': image}.items():
            put(storage/key, value)
        (conf/'mass_storage.boot').symlink_to(storage)
        put(BASE/'UDC', controllers[0].name)
        # Resolve function devices rather than assuming global hidg numbering.
        import os, stat, time
        def device_for(function):
            target = (BASE/'functions'/function/'dev').read_text().strip()
            for _ in range(30):
                for node in Path('/dev').glob('hidg*'):
                    st = node.stat()
                    if stat.S_ISCHR(st.st_mode) and f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}' == target:
                        return str(node)
                time.sleep(.1)
            raise ValueError('HID device node not created')
        config['keyboard'] = device_for('hid.keyboard')
        config['power'] = device_for('hid.power')
        config['udc_state'] = str(controllers[0]/'state')
        runtime = Path('/run/imac-tdm-controller')
        runtime.mkdir(mode=0o700, exist_ok=True)
        output = runtime/'config.json'
        output.write_text(json.dumps(config))
        output.chmod(0o600)
    except BaseException:
        stop()
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('start', 'stop'))
    p.add_argument('--config', default='/etc/imac-tdm-controller/config.json')
    args = p.parse_args()
    if args.action == 'stop':
        stop()
    else:
        start(json.loads(Path(args.config).read_text()))


if __name__ == '__main__':
    main()

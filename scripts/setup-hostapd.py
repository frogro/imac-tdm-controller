#!/usr/bin/env python3
"""Switch an installed dedicated Pi controller to a WPA2 hostapd access point."""
import configparser
import os
from pathlib import Path
import shutil
import subprocess


def configuration(ssid, password):
    if not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password) <= 63:
        raise ValueError('Invalid SSID or password length')
    if any(c in ssid + password for c in '\r\n\x00'):
        raise ValueError('Invalid newline in wireless credentials')
    return {
        '/etc/imac-tdm-controller/hostapd.conf': (
            'interface=wlan0\ndriver=nl80211\ncountry_code=DE\n'
            f'ssid={ssid}\nhw_mode=g\nchannel=6\nwmm_enabled=1\nauth_algs=1\n'
            f'wpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\nwpa_passphrase={password}\n'),
        '/etc/imac-tdm-controller/dnsmasq.conf': (
            'interface=wlan0\nbind-interfaces\nport=0\n'
            'dhcp-range=192.168.77.10,192.168.77.254,255.255.255.0,1h\n'
            'dhcp-option=3\ndhcp-option=6\ndhcp-leasefile=/run/imac-tdm-dhcp.leases\n'),
        '/etc/NetworkManager/conf.d/imac-tdm-unmanaged.conf':
            '[keyfile]\nunmanaged-devices=interface-name:wlan0\n',
        '/etc/systemd/system/imac-tdm-ap-address.service': '''[Unit]
Description=Address and route for the dedicated TDM access point
Requires=NetworkManager.service
After=NetworkManager.service sys-subsystem-net-devices-wlan0.device
Wants=sys-subsystem-net-devices-wlan0.device
Before=imac-tdm-ap.service imac-tdm-dhcp.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/nmcli device set wlan0 managed no
ExecStart=/usr/sbin/ip link set wlan0 up
ExecStart=/usr/sbin/ip address replace 192.168.77.1/24 dev wlan0
ExecStart=/usr/sbin/ip route replace 192.168.77.0/24 dev wlan0 src 192.168.77.1
''',
        '/etc/systemd/system/imac-tdm-ap.service': '''[Unit]
Description=TDM WPA2 access point
Requires=imac-tdm-ap-address.service
After=imac-tdm-ap-address.service
[Service]
ExecStart=/usr/sbin/hostapd /etc/imac-tdm-controller/hostapd.conf
Restart=on-failure
RestartSec=3
''',
        '/etc/systemd/system/imac-tdm-dhcp.service': '''[Unit]
Description=Local DHCP for TDM buttons
Requires=imac-tdm-ap-address.service
After=imac-tdm-ap-address.service
[Service]
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=/etc/imac-tdm-controller/dnsmasq.conf
Restart=on-failure
RestartSec=3
''',
        '/etc/systemd/system/imac-tdm-controller.service.d/hostapd.conf': '''[Unit]
Requires=imac-tdm-ap.service imac-tdm-dhcp.service
After=imac-tdm-ap.service imac-tdm-dhcp.service
[Service]
ExecStartPre=
''',
    }


def main():
    model = Path('/proc/device-tree/model')
    if not model.exists() or 'Raspberry Pi Zero' not in model.read_text():
        raise SystemExit('Run on the dedicated Pi Zero controller')
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo')
    for command in ('/usr/sbin/hostapd', '/usr/sbin/dnsmasq', '/usr/sbin/ip'):
        if not Path(command).exists():
            raise SystemExit('Install hostapd, dnsmasq-base and iproute2 first')
    source = Path('/etc/NetworkManager/system-connections/imac-tdm.nmconnection')
    if not Path('/etc/imac-tdm-controller/config.json').exists():
        raise SystemExit('Install the controller with install-pi.py first')
    c = configparser.ConfigParser(interpolation=None)
    c.read(source)
    files = configuration(c['wifi']['ssid'], c['wifi-security']['psk'])
    backup = Path('/etc/imac-tdm-controller/networkmanager-backup.nmconnection')
    if not backup.exists():
        shutil.copyfile(source, backup)
        backup.chmod(0o600)
    for name, content in files.items():
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o600 if path.suffix == '.conf' and 'imac-tdm-controller/' in name else 0o644)
    # Keep the former AP profile for recovery, but do not activate it automatically.
    c['connection']['autoconnect'] = 'false'
    with source.open('w') as f:
        c.write(f, space_around_delimiters=False)
    source.chmod(0o600)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('Hostapd configured. Changes take effect on next reboot; credentials unchanged.')


if __name__ == '__main__':
    main()

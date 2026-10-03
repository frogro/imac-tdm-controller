#!/usr/bin/env python3
"""Read the running iMac Linux EFI boot target. Does not change firmware settings."""
import json
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def inspect(efi, disks):
    match = re.search(r'^BootCurrent:\s*([0-9A-Fa-f]{4})\s*$', efi, re.M)
    if not match:
        raise ValueError('Kein EFI-BootCurrent. Legacy/BIOS-Boot wird noch nicht unterstützt.')
    entry = re.search(r'^Boot'+match[1]+r'\*?\s+(.+)$', efi, re.M|re.I)
    if not entry:
        raise ValueError('Aktueller EFI-Starteintrag fehlt.')
    part = re.search(r'HD\(\d+,GPT,([0-9a-f-]+),', entry[1], re.I)
    loader = re.search(r'(?:File)?\((\\[^)]+\.efi)\)', entry[1], re.I)
    if not part or not loader:
        raise ValueError('EFI-Partition oder Loader nicht eindeutig; manuell mit efibootmgr -v prüfen.')
    def walk(nodes, usb=False):
        for node in nodes:
            external = usb or node.get('tran') == 'usb'
            if (node.get('partuuid') or '').lower() == part[1].lower():
                if external:
                    raise ValueError('Aktuelles System wurde von USB gestartet. Im internen Linux ausführen.')
                if node.get('fstype') not in ('vfat','fat','fat32') or not node.get('uuid'):
                    raise ValueError('Erwartete interne FAT-EFI-Partition nicht gefunden.')
                return dict(internal_uuid=node['uuid'], internal_loader=loader[1].replace('\\','/'))
            result = walk(node.get('children',[]),external)
            if result:return result
    result=walk(disks)
    if result is None:raise ValueError('EFI-Partition keinem lokalen Laufwerk zugeordnet.')
    return result


if __name__ == '__main__':
    try:
        result=inspect(run('efibootmgr','-v'),json.loads(run('lsblk','--json','--tree','--output','NAME,TRAN,FSTYPE,UUID,PARTUUID'))['blockdevices'])
        print(json.dumps(result,indent=2))
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))

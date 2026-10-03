#!/usr/bin/env python3
"""Build a new regular image file. Never opens or partitions a real disk."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Pin upstream sources, installer and boot payload to one reviewed commit.
UPSTREAM = 'ae161a92deb09950d4419b2a60188cc7b92ac623'


def run(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def cpio_entry(name, data, mode, inode):
    name = name.encode() + b'\0'
    fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0)
    record = b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + name
    record += b'\0' * (-len(record) % 4)
    return record + data + b'\0' * (-len(data) % 4)


def state_offset(fat, disk_offset=1024**2):
    """Find the preallocated root STATE.ENV file in FAT32, require contiguous data."""
    with fat.open('rb') as f:
        sector = f.read(512)
        bps = struct.unpack_from('<H', sector, 11)[0]
        spc = sector[13]
        reserved = struct.unpack_from('<H', sector, 14)[0]
        fats = sector[16]
        fatsz = struct.unpack_from('<I', sector, 36)[0]
        cluster = struct.unpack_from('<I', sector, 44)[0]
        data_start = (reserved + fats*fatsz)*bps
        def offset(c): return data_start + (c-2)*spc*bps
        def next_cluster(c):
            f.seek(reserved*bps+c*4)
            return struct.unpack('<I', f.read(4))[0] & 0x0fffffff
        seen = set()
        while 2 <= cluster < 0x0ffffff8 and cluster not in seen:
            seen.add(cluster)
            f.seek(offset(cluster))
            data = f.read(spc*bps)
            for start in range(0, len(data), 32):
                entry = data[start:start+32]
                if entry[:11] == b'STATE   ENV':
                    first = struct.unpack_from('<H', entry, 26)[0] | struct.unpack_from('<H', entry, 20)[0] << 16
                    size = struct.unpack_from('<I', entry, 28)[0]
                    if size != 1024:
                        raise ValueError('Unexpected GRUB environment size')
                    for c in range(first, first+(size-1)//(spc*bps)):
                        if next_cluster(c) != c+1:
                            raise ValueError('GRUB state must be contiguous')
                    return disk_offset + offset(first)
            cluster = next_cluster(cluster)
    raise ValueError('STATE.ENV missing')


def grub_config(uuid=None, loader=None, *, tdm_only=False, tdm_autostart=False):
    if tdm_only and tdm_autostart:
        raise ValueError('Choose either --tdm-only or --tdm-autostart')
    monitor_only = tdm_only or tdm_autostart
    if monitor_only:
        if uuid or loader:
            raise ValueError('Monitor-only modes do not accept an internal boot target')
    else:
        if not isinstance(uuid, str) or not re.fullmatch(r'[A-Za-z0-9-]+', uuid):
            raise ValueError('Invalid filesystem UUID')
        if not isinstance(loader, str) or not re.fullmatch(r'/[A-Za-z0-9_./+-]+\.efi', loader) or '..' in loader.split('/'):
            raise ValueError('Expected an absolute EFI loader path without spaces or traversal')
    config = f'''set timeout={0 if tdm_autostart else -1}
set default=0
set timeout_style=menu
search --no-floppy --label TINYCORE --set=tdm_disk
set root=$tdm_disk
set phase=menu
if save_env -f ($tdm_disk)/STATE.ENV phase; then
  echo "Controller bereit"
else
  echo "Controller-Status konnte nicht gespeichert werden; normale Tastatur verwenden."
fi
menuentry "TinyCore - Monitorbetrieb (kurz / T)" --hotkey=t {{
  set timeout=-1
  set root=$tdm_disk
  if linux /boot/vmlinuz loglevel=3 kmap=qwertz/de-latin1 waitusb=10 tce=LABEL=TINYCORE tdm_autostart=1; then
    if initrd /boot/corepure64.gz /boot/custom.gz /boot/controller.gz; then
      set phase=tinycore
      save_env -f ($tdm_disk)/STATE.ENV phase
      boot
    fi
  fi
  echo "TinyCore konnte nicht gestartet werden."
  set phase=menu
  save_env -f ($tdm_disk)/STATE.ENV phase
  sleep 3
}}
'''
    if monitor_only:
        config += '''menuentry "Poweroff - Ausschalten (lang / L)" --hotkey=l {
  set timeout=-1
  halt
  echo "Ausschalten fehlgeschlagen. Bitte den Einschaltknopf verwenden."
  set phase=menu
  save_env -f ($tdm_disk)/STATE.ENV phase
  sleep 3
}
'''
    else:
        config += f'''
menuentry "Internes Linux (lang / L)" --hotkey=l {{
  if search --no-floppy --fs-uuid --set=internal {uuid}; then
    if chainloader ($internal){loader}; then
      set phase=linux
      save_env -f ($tdm_disk)/STATE.ENV phase
      boot
    fi
  fi
  echo "Internes EFI-Linux konnte nicht gestartet werden."
  set phase=menu
  save_env -f ($tdm_disk)/STATE.ENV phase
  sleep 3
}}
'''
    return config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--internal-uuid', help='Filesystem UUID of the internal EFI partition')
    p.add_argument('--internal-loader', help='e.g. /EFI/ubuntu/shimx64.efi')
    p.add_argument('--source', type=Path, help='Offline tinycore-tdm checkout including scripts and optional packages')
    p.add_argument('--ssh-key', type=Path, help='Optional public key for TinyCore maintenance')
    p.add_argument('--internal-config', type=Path, help='JSON from inspect-linux.py on the iMac')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--tdm-only', action='store_true', help='Monitor-only: wait in GRUB, no internal disk required')
    mode.add_argument('--tdm-autostart', action='store_true', help='Monitor-only: boot TinyCore immediately, no internal disk required')
    args = p.parse_args()
    monitor_only = args.tdm_only or args.tdm_autostart
    if monitor_only and (args.internal_config or args.internal_uuid or args.internal_loader):
        p.error('Monitor-only modes cannot be combined with an internal boot target')
    if args.internal_config:
        if args.internal_uuid or args.internal_loader:
            p.error('Use --internal-config or the two explicit target flags')
        target = json.loads(args.internal_config.read_text())
        args.internal_uuid = target['internal_uuid']
        args.internal_loader = target['internal_loader']
    if not monitor_only and (not args.internal_uuid or not args.internal_loader):
        p.error('Provide an internal boot target, --tdm-only or --tdm-autostart')
    config_text = grub_config(args.internal_uuid, args.internal_loader,
                              tdm_only=args.tdm_only, tdm_autostart=args.tdm_autostart)
    output = args.output.resolve()
    if output.exists() or output.with_suffix('.json').exists():
        p.error('Output must be new; existing files are never overwritten')
    for command in ('gcc', 'grub-mkstandalone', 'grub-editenv', 'mkfs.vfat', 'sfdisk', 'mcopy'):
        if shutil.which(command) is None:
            p.error('Missing build tool: ' + command)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tdm-build-', dir=output.parent) as tmp:
        work = Path(tmp)
        if args.source:
            source = args.source.resolve()
            installer = source/'scripts/install-usb.py'
        else:
            source = work/'source'
            source.mkdir()
            installer = work/'installer.py'
            url = f'https://raw.githubusercontent.com/frogro/tinycore-tdm/{UPSTREAM}/scripts/install-usb.py'
            with urllib.request.urlopen(url, timeout=60) as response:
                installer.write_bytes(response.read())
        spec = importlib.util.spec_from_file_location('upstream_installer', installer)
        upstream = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(upstream)
        if not args.source:
            upstream.download_payload(source, UPSTREAM, 'de', bool(args.ssh_key))
            url = f'https://raw.githubusercontent.com/frogro/tinycore-tdm/{UPSTREAM}/opt/bootlocal.sh'
            (source/'opt').mkdir()
            with urllib.request.urlopen(url, timeout=60) as response:
                (source/'opt/bootlocal.sh').write_bytes(response.read())
        payload = work/'payload'
        payload.mkdir()
        key = upstream.public_key(args.ssh_key) if args.ssh_key else None
        upstream.configure_payload(source, upstream.payload_files(source, 'de', bool(key)), payload, 'de', key)
        (payload/'grub.cfg').write_text(config_text)
        binary = work/'power-listener'
        run('gcc', '-static', '-Os', '-Wall', '-Wextra', '-Werror', '-o', str(binary), str(ROOT/'tinycore/power-listener.c'))
        # This binary runs on the x86_64 iMac, not on the Pi. Build on x86_64 Linux.
        elf = binary.read_bytes()
        if elf[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', elf, 18)[0] != 62:
            raise ValueError('Build on x86_64 Linux; TinyCore requires an x86_64 power listener')
        entries = []
        for name in ('opt', 'usr', 'usr/local', 'usr/local/sbin'):
            entries.append((name, b'', stat.S_IFDIR | 0o755))
        for name, data in [('opt/bootlocal.sh', (ROOT/'tinycore/bootlocal.sh').read_bytes()),
                           ('opt/tdm-upstream-bootlocal.sh', (source/'opt/bootlocal.sh').read_bytes()),
                           ('usr/local/sbin/tdm-power-listener', elf)]:
            entries.append((name, data, stat.S_IFREG | 0o755))
        entries.append(('TRAILER!!!', b'', 0))
        archive = b''.join(cpio_entry(n, d, m, j) for j, (n, d, m) in enumerate(entries, 1))
        (payload/'boot/controller.gz').write_bytes(gzip.compress(archive, mtime=0))
        embedded = work/'embedded.cfg'
        embedded.write_text('search --no-floppy --label TINYCORE --set=root\nconfigfile /grub.cfg\n')
        run('grub-mkstandalone', '-O', 'x86_64-efi', '--locales=', '--fonts=', '--modules=part_gpt fat search search_label search_fs_uuid normal configfile loadenv chain linux sleep halt',
            '-o', str(payload/'EFI/BOOT/BOOTX64.EFI'), f'boot/grub/grub.cfg={embedded}')
        run('grub-editenv', str(payload/'STATE.ENV'), 'create')
        run('grub-editenv', str(payload/'STATE.ENV'), 'set', 'phase=unknown')
        partition, image = work/'partition.fat', work/'disk.img'
        with partition.open('wb') as f: f.truncate(510*1024**2)
        run('mkfs.vfat', '-F', '32', '-n', 'TINYCORE', str(partition), stdout=subprocess.DEVNULL)
        # Allocate state first so it is contiguous; record its data offset once.
        run('mcopy', '-i', str(partition), str(payload/'STATE.ENV'), '::/')
        offset = state_offset(partition)
        for name in ('EFI', 'boot', 'grub.cfg', 'tce'):
            run('mcopy', '-s', '-i', str(partition), str(payload/name), '::/')
        with image.open('wb') as f: f.truncate(512*1024**2)
        run('sfdisk', str(image), input=b'label: gpt\nunit: sectors\n\nstart=2048,size=1044480,type=U,name=TINYCORE\n', stdout=subprocess.DEVNULL)
        with image.open('r+b') as out, partition.open('rb') as src:
            out.seek(1024**2)
            shutil.copyfileobj(src, out)
        metadata = dict(state_offset=offset, image_size=image.stat().st_size,
                        sha256=hashlib.sha256(image.read_bytes()).hexdigest(), upstream_commit=UPSTREAM,
                        internal_uuid=args.internal_uuid, internal_loader=args.internal_loader,
                        boot_mode='tdm-autostart' if args.tdm_autostart else 'tdm-only' if args.tdm_only else 'dual')
        # Exclusive publication: never replace a concurrently created output.
        os.link(image, output)
        with output.with_suffix('.json').open('x') as f:
            json.dump(metadata, f, indent=2)
        print(f'{output}\n{output.with_suffix(".json")}')


if __name__ == '__main__':
    main()

"""Pure protocol and state helpers; no host shutdown commands live on the Pi."""
import hmac
import os
import secrets
import time

GRUB_HEADER = b'# GRUB Environment Block\n'
PHASES = {'menu', 'tinycore', 'linux'}
# Boot keyboard (8-byte reports), and a separate Generic Desktop/System Control HID.
KEYBOARD_DESCRIPTOR = bytes.fromhex(
    '05010906a101050719e029e715002501750195088102950175088103'
    '95057501050819012905910295017503910395067508150025650507190029658100c0')
POWER_DESCRIPTOR = bytes.fromhex('05010980a101150025010981750195018102750795018103c0')


def read_phase(image, offset):
    """Read only; never mount or write the image owned by the USB host.

    GRUB writes a preallocated 1 KiB environment block. Two equal reads reject
    an observable torn update; a phase is not proof that an OS finished booting.
    """
    fd = os.open(image, os.O_RDONLY)
    try:
        first = os.pread(fd, 1024, offset)
        second = os.pread(fd, 1024, offset)
    finally:
        os.close(fd)
    if first != second or len(first) != 1024 or not first.startswith(GRUB_HEADER):
        return 'unknown'
    lines = first.split(b'\n')
    values = [line[6:].decode('ascii', errors='replace') for line in lines if line.startswith(b'phase=')]
    return values[0] if len(values) == 1 and values[0] in PHASES else 'unknown'


def action_for(phase, gesture):
    if gesture not in ('short', 'long'):
        raise ValueError('Unknown gesture')
    if phase == 'menu':
        return 'boot_tinycore' if gesture == 'short' else 'boot_linux'
    if phase in ('tinycore', 'linux'):
        return 'none' if gesture == 'short' else 'power'
    return 'unavailable'


class Tickets:
    """One-use, short-lived commands bound to the phase seen by the button."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.entries = {}

    def issue(self, phase):
        now = self.clock()
        self.entries = {k: v for k, v in self.entries.items() if now < v['expires']}
        if len(self.entries) >= 128:
            raise ValueError('Too many pending events')
        token = secrets.token_hex(24)
        self.entries[token] = dict(expires=now+5, phase=phase, result=None)
        return token

    def take(self, token, phase, gesture):
        entry = self.entries.get(token)
        if entry is None or self.clock() >= entry['expires']:
            raise ValueError('Expired or unknown ticket')
        if entry['result'] is not None:
            return entry['result'], False
        # Consume before sending HID: a lost response must never repeat an action.
        action = action_for(phase, gesture) if phase == entry['phase'] else 'unavailable'
        entry['result'] = action
        return action, True


def authorized(header, token):
    return hmac.compare_digest((header or '').encode('utf-8'), ('Bearer ' + token).encode('utf-8'))

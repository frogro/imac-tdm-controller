#!/usr/bin/env python3
import argparse
import json
import logging
import os
from pathlib import Path
import select
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from controller.core import Tickets, authorized, read_phase


class HID:
    def __init__(self, keyboard, power):
        self.keyboard, self.power = keyboard, power

    @staticmethod
    def pulse(path, report, release):
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        def send(data):
            deadline = time.monotonic() + 1
            while True:
                try:
                    if os.write(fd, data) != len(data):
                        raise OSError('Short HID report')
                    return
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                        raise TimeoutError('HID host did not accept report')
        try:
            send(report)
            time.sleep(0.06)
        finally:
            try:
                send(release)
            finally:
                os.close(fd)

    def perform(self, action):
        if action in ('boot_tinycore', 'boot_linux'):
            # GRUB hotkeys: t / l. No Enter and no modifier needed.
            code = 0x17 if action == 'boot_tinycore' else 0x0f
            self.pulse(self.keyboard, bytes([0, 0, code, 0, 0, 0, 0, 0]), bytes(8))
        elif action == 'power':
            # Generic Desktop usage 0x81 System Power Down, one-bit press/release reports.
            self.pulse(self.power, b'\x01', b'\x00')


class Application:
    def __init__(self, config, hid=None, clock=time.monotonic):
        self.config = config
        self.hid = hid or HID(config['keyboard'], config['power'])
        self.clock = clock
        self.tickets = Tickets(clock)
        self.blocked_until = 0

    def phase(self):
        udc = Path(self.config['udc_state'])
        if not udc.exists() or udc.read_text().strip() != 'configured':
            return 'unknown'
        try:
            return read_phase(self.config['image'], self.config['state_offset'])
        except OSError:
            return 'unknown'

    def event(self, payload):
        gesture = payload.get('gesture')
        if gesture not in ('short', 'long') or not isinstance(payload.get('ticket'), str):
            raise ValueError('Invalid event')
        action, fresh = self.tickets.take(payload['ticket'], self.phase(), gesture)
        if fresh and action not in ('none', 'unavailable'):
            if self.clock() < self.blocked_until:
                self.tickets.entries[payload['ticket']]['result'] = 'unavailable'
                return 'unavailable'
            # Guard against repeated presses during boot; this is not a ready signal.
            self.blocked_until = self.clock() + (20 if action.startswith('boot_') else 5)
            try:
                self.hid.perform(action)
            except OSError:
                self.tickets.entries[payload['ticket']]['result'] = 'unavailable'
                raise
        return action


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def authenticated(self):
            if not authorized(self.headers.get('Authorization'), app.config['token']):
                self.reply(401, {'error': 'Unauthorized'})
                return False
            return True

        def do_GET(self):
            if not self.authenticated():
                return
            phase = app.phase()
            if self.path == '/status':
                self.reply(200, {'phase': phase, 'meaning': 'GRUB selection, not actual display state'})
            elif self.path == '/ticket':
                try:
                    ticket = app.tickets.issue(phase)
                    self.reply(200, {'ticket': ticket, 'phase': phase})
                except ValueError as error:
                    self.reply(429, {'error': str(error)})
            else:
                self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.authenticated():
                return
            if self.path != '/event':
                self.reply(404, {'error': 'Not found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 512 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request length')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected JSON object')
                self.reply(200, {'action': app.event(payload)})
            except (ValueError, TypeError) as error:
                self.reply(400, {'error': str(error)})
            except OSError:
                logging.exception('USB HID event failed')
                self.reply(503, {'error': 'USB host unavailable; action not retried'})

        def log_message(self, fmt, *args):
            logging.info(fmt, *args)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/imac-tdm-controller/config.json')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if len(config.get('token', '')) < 32:
        raise ValueError('Configure a random token of at least 32 characters')
    logging.basicConfig(level=logging.INFO)
    server = HTTPServer((config.get('listen', '192.168.77.1'), config.get('port', 8080)), handler_for(Application(config)))
    server.serve_forever()


if __name__ == '__main__':
    main()

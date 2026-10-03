import importlib.util
import json
import socket
import tempfile
import threading
from pathlib import Path
import unittest
import urllib.request
import urllib.error
from unittest.mock import Mock, patch
from http.server import HTTPServer
from controller.core import Tickets, read_phase, GRUB_HEADER, action_for
from controller.server import Application, handler_for, HID

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('button', ROOT/'firmware/circuitpython/button.py')
button = importlib.util.module_from_spec(spec); spec.loader.exec_module(button)


class ButtonTests(unittest.TestCase):
    def test_short_only_on_release_and_debounce(self):
        b=button.Button(); b.update(False, .1)
        self.assertIsNone(b.update(True,.2))
        self.assertIsNone(b.update(False,.21))
        self.assertIsNone(b.update(False,.3))
        b.update(True,.4); self.assertIsNone(b.update(True,.45))
        self.assertIsNone(b.update(False,.6))
        self.assertEqual(b.update(False,.65),'short')
        self.assertIsNone(b.update(False,.8))

    def test_long_once_and_no_short_after_release(self):
        b=button.Button(); b.update(False,.1); b.update(True,.2); b.update(True,.25)
        self.assertEqual(b.update(True,3.3),'long')
        self.assertIsNone(b.update(True,5))
        b.update(False,5.1); self.assertIsNone(b.update(False,5.2))

    def test_held_at_boot_or_reconnect_is_ignored(self):
        b=button.Button(); b.update(True,.1); b.update(True,.2)
        self.assertIsNone(b.update(True,10))
        b.update(False,11); self.assertIsNone(b.update(False,11.1))
        b.update(True,12); b.update(True,12.1); b.reset()
        self.assertIsNone(b.update(True,20))
        b.update(False,21); self.assertIsNone(b.update(False,21.1))


class ControllerTests(unittest.TestCase):
    def test_mapping(self):
        expected={'menu':('boot_tinycore','boot_linux'),'tinycore':('none','power'),'linux':('none','power'),'unknown':('unavailable','unavailable')}
        for phase, actions in expected.items():
            self.assertEqual(tuple(action_for(phase,g) for g in ('short','long')),actions)

    def test_tickets_expire_reject_phase_change_and_deduplicate(self):
        clock=Mock(return_value=0); tickets=Tickets(clock)
        t=tickets.issue('menu')
        self.assertEqual(tickets.take(t,'menu','long'),('boot_linux',True))
        self.assertEqual(tickets.take(t,'menu','long'),('boot_linux',False))
        t=tickets.issue('menu')
        self.assertEqual(tickets.take(t,'linux','long'),('unavailable',True))
        t=tickets.issue('linux'); clock.return_value=6
        with self.assertRaises(ValueError): tickets.take(t,'linux','long')

    def test_reads_only_valid_environment_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image'
            for phase in ('menu','tinycore','linux','unknown'):
                data=(GRUB_HEADER+f'phase={phase}\n'.encode()).ljust(1024,b'#')
                path.write_bytes(b'prefix'+data)
                self.assertEqual(read_phase(path,6),phase)
            path.write_bytes((GRUB_HEADER+b'phase=menu\nphase=linux\n').ljust(1024,b'#'))
            self.assertEqual(read_phase(path,0),'unknown')
            path.write_bytes(b'partial'); self.assertEqual(read_phase(path,0),'unknown')

    def test_duplicate_or_new_press_during_boot_does_not_poweroff(self):
        clock=Mock(return_value=0); hid=Mock(); app=Application({},hid,clock)
        app.phase=Mock(return_value='menu')
        t=app.tickets.issue('menu')
        self.assertEqual(app.event({'ticket':t,'gesture':'long'}),'boot_linux')
        app.event({'ticket':t,'gesture':'long'})
        hid.perform.assert_called_once_with('boot_linux')
        app.phase.return_value='linux'
        t=app.tickets.issue('linux')
        self.assertEqual(app.event({'ticket':t,'gesture':'long'}),'unavailable')
        clock.return_value=25; t=app.tickets.issue('linux')
        self.assertEqual(app.event({'ticket':t,'gesture':'long'}),'power')

    def test_failed_hid_is_not_retried(self):
        hid=Mock(); hid.perform.side_effect=OSError('disconnected')
        app=Application({},hid); app.phase=Mock(return_value='menu')
        t=app.tickets.issue('menu')
        with self.assertRaises(OSError): app.event({'ticket':t,'gesture':'short'})
        self.assertEqual(app.event({'ticket':t,'gesture':'short'}),'unavailable')
        self.assertEqual(hid.perform.call_count,1)

    def test_power_report_has_release(self):
        hid=HID('/keyboard','/power')
        with patch.object(hid,'pulse') as pulse:
            hid.perform('power'); pulse.assert_called_once_with('/power',b'\x01',b'\x00')

    def test_http_auth_and_real_request_deduplication(self):
        hid=Mock(); app=Application({'token':'x'*64},hid); app.phase=Mock(return_value='menu')
        server=HTTPServer(('127.0.0.1',0),handler_for(app))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url+'/ticket')
            self.assertEqual(error.exception.code,401)
            error.exception.close()
            def request(path,payload=None):
                req=urllib.request.Request(url+path,data=json.dumps(payload).encode() if payload else None,
                    headers={'Authorization':'Bearer '+'x'*64})
                with urllib.request.urlopen(req) as r:return json.load(r)
            ticket=request('/ticket')['ticket']; payload={'ticket':ticket,'gesture':'short'}
            self.assertEqual(request('/event',payload),{'action':'boot_tinycore'})
            self.assertEqual(request('/event',payload),{'action':'boot_tinycore'})
            hid.perform.assert_called_once_with('boot_tinycore')
        finally:
            server.shutdown(); server.server_close(); thread.join()

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT=Path(__file__).resolve().parents[1]
def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
button=module('installer','scripts/install-button.py')
build=module('builder','scripts/build-image.py')


class InstallerTests(unittest.TestCase):
    def test_board_settings_and_escaping(self):
        for board,pin in [('pico-w','GP15'),('esp32','D4'),('esp32-devkitc','IO4'),('tinypico','IO25')]:
            data=button.settings_text(button.PROFILES[board],'A"B','abc"defgh','192.168.77.1','x'*64)
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'settings.toml';path.write_text(data)
                values=button.parse_settings(path)
                self.assertEqual(values['BUTTON_PIN'],pin)
                self.assertEqual(values['BUTTON_WIFI_PASSWORD'],'abc"defgh')

    def test_serial_console_retries_after_boot_and_closes_on_failure(self):
        serial = MagicMock()
        port = serial.Serial.return_value
        with patch.dict('sys.modules', {'serial': serial}), patch.object(button.time, 'sleep'):
            with patch.object(button.RawREPL, 'until', side_effect=[ValueError('booting'), b'raw REPL']):
                repl = button.RawREPL('/dev/test')
                self.assertEqual(port.write.call_count, 4)
                repl.close()
            port.reset_mock()
            with patch.object(button.RawREPL, 'until', side_effect=ValueError('offline')):
                with self.assertRaises(ValueError):
                    button.RawREPL('/dev/test')
                self.assertEqual(port.write.call_count, 6)
                port.close.assert_called_once()

    def test_firmware_corruption_rejected(self):
        with patch.object(button.urllib.request,'urlopen') as fetch:
            fetch.return_value.__enter__.return_value.read.return_value=b'broken'
            with self.assertRaises(ValueError):button.firmware_data('pico-w')

    def test_mount_validation_rejects_wrong_board_and_nonmount(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'boot_out.txt').write_text('CircuitPython\nBoard ID:wrong\n')
            with self.assertRaises(ValueError):button.validate_mount(path,'circuitpy')
            with patch.object(button.os.path,'ismount',return_value=True):
                with self.assertRaises(ValueError):button.validate_mount(path,'circuitpy')
                (path/'boot_out.txt').write_text('CircuitPython\nBoard ID:raspberry_pi_pico_w\n')
                self.assertEqual(button.validate_mount(path,'circuitpy'),path)

    def test_grub_configuration_and_injection_rejected(self):
        config=build.grub_config('ABCD-1234','/EFI/ubuntu/shimx64.efi')
        self.assertIn('set timeout=-1',config)
        self.assertIn('set phase=menu',config)
        self.assertIn('--hotkey=t',config)
        self.assertIn('--hotkey=l',config)
        self.assertNotIn('savedefault',config)
        for uuid,loader in [('bad;halt','/EFI/a.efi'),('1234','/EFI/../a.efi'),('1234','/EFI/a.efi;halt')]:
            with self.assertRaises(ValueError):build.grub_config(uuid,loader)

    def test_pi_reuses_button_credentials_and_rejects_wrong_endpoint(self):
        pi = module('pi_installer', 'scripts/install-pi.py')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.toml'
            text = button.settings_text(button.PROFILES['tinypico'], 'iMac-TDM', 'test-password', '192.168.77.1', 'a'*64)
            path.write_text(text)
            result = pi.load_button_settings(path)
            self.assertEqual(result['CONTROLLER_TOKEN'], 'a'*64)
            self.assertEqual(result['BUTTON_WIFI_PASSWORD'], 'test-password')
            path.write_text(text.replace('192.168.77.1', '192.168.77.2'))
            with self.assertRaises(ValueError): pi.load_button_settings(path)
            path.write_text(text.replace('a'*64, 'short'))
            with self.assertRaises(ValueError): pi.load_button_settings(path)

    def test_pi_stock_cm5_overlay_does_not_block_zero(self):
        pi = module('pi_overlay', 'scripts/install-pi.py')
        self.assertFalse(pi.has_existing_dwc2('[cm5]\ndtoverlay=dwc2,dr_mode=host\n[all]\n'))
        self.assertFalse(pi.has_existing_dwc2('#dtoverlay=dwc2\n'))
        self.assertTrue(pi.has_existing_dwc2('[all]\ndtoverlay=dwc2,dr_mode=peripheral\n'))
        self.assertTrue(pi.has_existing_dwc2('[pi0]\ndtoverlay = dwc2\n'))

    def test_pi_installer_refuses_build_host(self):
        # No privileges requested and no files changed on this non-Pi test machine.
        if Path('/proc/device-tree/model').exists():self.skipTest('Run this assertion on a non-Pi host')
        result=subprocess.run(['python3',str(ROOT/'scripts/install-pi.py'),'--image','unused.img'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Run this installer on',result.stderr)

    def test_prepare_only_for_all_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.toml'
            settings.write_text(button.settings_text(button.PROFILES['pico-w'],'iMac-TDM','test-password','192.168.77.1','x'*64))
            for index,key in enumerate(button.PROFILES,1):
                result=subprocess.run(['python3',str(ROOT/'scripts/install-button.py'),'--settings',str(settings),'--prepare-only',str(root/key)],input=str(index)+'\n',text=True,capture_output=True,check=True)
                self.assertIn(button.PROFILES[key]['wire'],result.stdout)
                self.assertNotIn('test-password',result.stdout)
                self.assertEqual(button.parse_settings(root/key/'settings.toml')['BUTTON_PIN'],button.PROFILES[key]['pin'])
                self.assertEqual((root/key/'code.py').read_bytes(),(ROOT/'firmware/circuitpython/code.py').read_bytes())

class BootTargetTests(unittest.TestCase):
    def test_current_efi_target_and_usb_rejection(self):
        helper=module('inspect_linux','scripts/inspect-linux.py')
        efi='BootCurrent: 0002\nBoot0002* ubuntu HD(1,GPT,abcd-1234,0x800,0x1000)/File(\\EFI\\ubuntu\\shimx64.efi)\n'
        disk={'name':'sda','tran':'sata','children':[{'name':'sda1','partuuid':'abcd-1234','fstype':'vfat','uuid':'ABCD-5678'}]}
        self.assertEqual(helper.inspect(efi,[disk]),{'internal_uuid':'ABCD-5678','internal_loader':'/EFI/ubuntu/shimx64.efi'})
        disk['tran']='usb'
        with self.assertRaises(ValueError):helper.inspect(efi,[disk])
        with self.assertRaises(ValueError):helper.inspect('BootCurrent: 0001\nBoot0001* Legacy\n',[])

class MonitorModeTests(unittest.TestCase):
    def test_monitor_modes_do_not_reference_internal_disks(self):
        for flag, timeout in [('tdm_only', -1), ('tdm_autostart', 0)]:
            config = build.grub_config(**{flag: True})
            self.assertTrue(config.startswith(f'set timeout={timeout}\n'))
            self.assertNotIn('chainloader', config)
            self.assertNotIn('--fs-uuid', config)
            self.assertNotIn('set phase=linux', config)
            self.assertIn('--hotkey=t', config)
            self.assertIn('--hotkey=l', config)
            self.assertIn('Kein internes Linux eingerichtet', config)
            # Failed autostart must stop at the menu rather than loop.
            self.assertIn('  set timeout=-1\n  set root=$tdm_disk\n  if linux', config)

    def test_conflicting_modes_or_targets_rejected_before_build(self):
        for flags in [
            ['--tdm-only', '--tdm-autostart'],
            ['--tdm-only', '--internal-uuid', '1234', '--internal-loader', '/EFI/test.efi'],
            ['--tdm-autostart', '--internal-config', '/does/not/exist'],
        ]:
            with tempfile.TemporaryDirectory() as tmp:
                output=Path(tmp)/'out.img'
                result=subprocess.run(['python3',str(ROOT/'scripts/build-image.py'),'--output',str(output)]+flags,capture_output=True,text=True)
                self.assertEqual(result.returncode,2)
                self.assertFalse(output.exists())
        with self.assertRaises(ValueError): build.grub_config(tdm_only=True,tdm_autostart=True)
        with self.assertRaises(ValueError): build.grub_config('1234','/EFI/a.efi',tdm_only=True)

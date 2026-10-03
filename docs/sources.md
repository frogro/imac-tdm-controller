# Quellen und Lizenzhinweise

- Bootpayload und ursprüngliche TDM-Skripte: [frogro/tinycore-tdm](https://github.com/frogro/tinycore-tdm)
  in Commit `ae161a92deb09950d4419b2a60188cc7b92ac623`. Der Builder lädt dieses
  Repository und prüft die dort veröffentlichten Größen/SHA-256. Komponenten
  behalten ihre jeweiligen Lizenzen; insbesondere SmcDumpKey unter GPLv2.
- GRUB wird mit den Werkzeugen des Buildsystems erzeugt; GNU GRUB steht unter GPLv3+.
- Linux-Gadget-Dokumentation: [HID](https://www.kernel.org/doc/html/latest/usb/gadget_hid.html),
  [Massenspeicher](https://www.kernel.org/doc/html/latest/usb/mass-storage.html).
- CircuitPython 10.3.1: [Pico W](https://circuitpython.org/board/raspberry_pi_pico_w/),
  [ESP32 DevKit v1](https://circuitpython.org/board/doit_esp32_devkit_v1/),
  [ESP32-WROOM-32E](https://circuitpython.org/board/espressif_esp32_devkitc_v4_wroom_32e/).
  Firmware wird von `downloads.circuitpython.org` geladen. `firmware/releases.json`
  enthält die bei der Einrichtung ermittelten SHA-256-Werte. Die Firmware wird
  nicht als eigene Entwicklung ausgegeben oder im Repository dupliziert.
- ESP32-Flashverfahren: [Adafruit ESPTool-Anleitung](https://learn.adafruit.com/circuitpython-with-esp32-quick-start/command-line-esptool).

Die hier neu geschriebenen Projektdateien stehen unter der MIT-Lizenz in LICENSE.
Das ändert keine Lizenzen heruntergeladener oder vom Buildsystem eingebundener
Komponenten. Images für private Tests werden lokal erzeugt; dieses Repository
verteilt keine fremden Binärpakete als Release-Image.

# Tests und Grenzen

## Lokal durchgeführt

- 19 automatisierte Tests mit Python `unittest`: Entprellung, kurzer/langer Druck,
  kein zusätzlicher Kurzdruck nach langem Halten, kein Befehl bei gedrücktem Taster
  nach Neustart/Verbindungswechsel, Zustandstabelle, Ticketablauf und doppelte
  Requests, Phasenwechsel, Sperre während Boot, HID-Schreibfehler, Power-Release,
  authentifizierte HTTP-Anfragen an einen echten lokalen Testserver.
- Installer: Konfigurationsquotierung, Boardprofile/Pinangaben, Ablehnung falscher
  Laufwerke, fehlerhafte Firmwareprüfsummen, Prepare-only für alle vier Profile,
  GRUB-Konfigurationsvalidierung, automatische EFI-Zielerkennung und Ablehnung des Pi-Installers auf dem Build-PC.
- Syntaxprüfung der Python-/Shell-Dateien und statisches Kompilieren des
  TinyCore-Empfängers mit `-Wall -Wextra -Werror`.
- CircuitPython 10.3.1 für Pico W, ESP32 DevKit v1, ESP32-DevKitC V4/WROOM-32E und TinyPICO
  vom offiziellen Downloadserver geladen und die SHA-256-Werte festgehalten.

## QEMU/UEFI

Ein virtuelles 512-MiB-USB-Laufwerk wurde mit dem Image-Builder erstellt und unter
QEMU mit OVMF gestartet. Geprüft:

1. GRUB startet und wartet ohne Zeitlimit. Der Statusbereich meldet `menu`.
2. Nicht vorhandener interner EFI-Loader führt zurück zum Menü; Status bleibt `menu`.
3. Taste `t` startet TinyCore bis zur Konsole; Status wird `tinycore`.
4. `/usr/local/sbin/tdm-power-listener` läuft im Gast, deutsches Layout ist geladen.
5. Ein normaler Gast-Neustart startet wieder GRUB; der Status wird erneut `menu`.
6. Ein zweites virtuelles Laufwerk mit passender UUID und einem EFI-Testloader wird
   über Taste `l` gestartet. Der Testloader meldet `INTERNAL_EFI_CHAINLOAD_OK` auf
   der seriellen Testkonsole; der Controllerstatus lautet `linux`.

Der zweite Bootpfad prüft die Übergabe an einen EFI-Loader, nicht jede Linux-
Distribution. Die Tests verwenden ausschließlich Dateien als virtuelle Laufwerke.
Der originale USB-Stick und das interne Laufwerk des Nutzers werden nicht beschrieben.

## Noch am Gerät prüfen

- Pi-Gadget-Erkennung in der alten iMac-Firmware und beim Übergang nach Linux.
- Reale Pico-/ESP32-Flashinstallation, GPIO-Taster, AP-Verbindung und Funkabbrüche.
- HID-System-Power-Ereignis und sauberes Herunterfahren in TinyCore und dem
  verwendeten internen Linux, einschließlich Desktop-Energieverwaltung.
- Neustarts, USB-Verbindungsverlust, Suspend, Pi-Dienstneustart und Stromversorgung.
- Dauerhaftes Startziel im Apple-EFI, Verhalten ohne angeschlossenen Pi und
  tatsächlicher interner EFI-Loader.
- Tatsächliche TDM-Umschaltung und rein lesende SMC-Zustandserkennung.

Es wurden keine physischen Boards als getestet ausgegeben. QEMU kann weder die
SMC-Hardwareumschaltung noch das WLAN oder die Pi-USB-Hardware nachweisen.

## Wiederholen

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q controller scripts firmware/circuitpython
gcc -static -Os -Wall -Wextra -Werror -o /tmp/tdm-power-listener tinycore/power-listener.c
```

## Monitor-Modi

Zusätzliche Tests prüfen beide Konfigurationen ohne internes Bootziel sowie
unzulässige Kombinationen von Modus und interner Partition. Für beide Modi wurden
vollständige Images erzeugt. Der Autostart bootet in QEMU ohne Tastenaktion und ohne
zusätzliches internes Laufwerk bis zur TinyCore-Konsole (`phase=tinycore`).
Der wartende Modus bleibt nach `l` mit dem Hinweis auf das fehlende interne Linux
im Menü (`phase=menu`); `t` startet anschließend TinyCore (`phase=tinycore`).

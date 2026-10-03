# iMac TDM Controller

Ein WLAN-Taster entscheidet, ob ein **iMac 27″ Ende 2009** als Monitor oder als
Linux-Rechner startet. Ein **Pi Zero W oder Zero 2 W** stellt das USB-Bootmedium
und eine USB-Tastatur mit Power-Taste bereit. Der Taster ist ein **Pico W oder
ESP32 mit demselben CircuitPython-Code**.

```text
WLAN-Taster ── eigenes Pi-WLAN ── Pi Zero (2) W ── USB ── iMac
                                Bootmedium + HID
```

| Zustand | Kurz drücken | 3 Sekunden halten |
| --- | --- | --- |
| GRUB wartet ohne Zeitlimit | TinyCore und TDM starten | Internes Linux starten |
| TinyCore/TDM ausgewählt | Keine Aktion | Power-Taste: herunterfahren |
| Internes Linux ausgewählt | Keine Aktion | Power-Taste: herunterfahren |

Ein kurzer Druck wird erst beim Loslassen ausgelöst. Ein langer Druck löst
nur einmal aus und sendet beim Loslassen keine zusätzliche Aktion. Nach einer
Bootauswahl werden weitere Aktionen 20 Sekunden gesperrt. Ein während einer
WLAN-Unterbrechung gedrückter Taster führt später keine Aktion aus.

**Erste Implementierung für Hardwaretests.** Die Logik ist automatisiert geprüft;
Bootabläufe werden mit QEMU getestet. USB-Gadget, WLAN und Power-Taste müssen noch
mit Pi, Taster und iMac gemeinsam geprüft werden. Der tatsächliche Displayzustand
wird noch nicht ermittelt. Details stehen in [Tests und Grenzen](docs/testing.md).

## Benötigt

- Pi Zero W oder Zero 2 W mit microSD und Raspberry Pi OS Lite mit NetworkManager.
  Für den ursprünglichen Zero W die **32-Bit-Ausgabe** verwenden.
- USB-Datenverbindung vom Pi-Port **USB**, nicht **PWR IN**, zum iMac.
- Pico W oder ein üblicher **ESP32 DevKit v1 mit ESP32-WROOM-32 und 4 MB Flash**,
  alternativ ESP32-DevKitC V4/WROOM-32E oder **TinyPICO V3 USB-C**,
  und ein normal offener Taster.
  S2/S3/C3 benötigen andere Firmware und werden nicht mit diesen Profilen geflasht.
- Ein x86_64-Linux-Rechner zum Erzeugen des Bootimages.
- Nur für die Wahl zwischen Monitor und Rechner: ein internes Linux mit
  **EFI-Bootloader**. Im reinen Monitorbetrieb ist keine HDD/SSD nötig.
  Alte BIOS/Legacy-Installationen werden
  von dieser ersten Fassung nicht automatisch gestartet.

Der Pi muss vor dem iMac betriebsbereit sein. Bei separater Stromversorgung eine
für USB-Gerätebetrieb geeignete Versorgung/Kabellösung ohne Rückspeisung verwenden.
Der Taster braucht eine eigene Versorgung, beispielsweise per USB oder beim
TinyPICO per LiPo-Akku. Tiefschlaf ist noch nicht umgesetzt; WLAN bleibt aktiv.

## 1. Projekt herunterladen

```sh
git clone https://github.com/frogro/imac-tdm-controller.git
cd imac-tdm-controller
```

## 2. Internes EFI-Bootziel ermitteln

Auf dem **iMac unter seinem internen Linux**:

```sh
sudo python3 scripts/inspect-linux.py > internal-linux.json
# Zur manuellen Kontrolle:
lsblk -f
sudo efibootmgr -v
```

Der Helfer ermittelt den aktuellen EFI-Loader und lehnt ein von USB gestartetes
System ab. Die erzeugte `internal-linux.json` auf den Buildrechner kopieren und
beim Imagebau mit `--internal-config internal-linux.json` verwenden. Falls keine
eindeutige automatische Zuordnung möglich ist:

Notiere die **Dateisystem-UUID der internen EFI-Partition** und den darin liegenden
EFI-Loader des Linux-Systems. Beispielsweise `ABCD-1234` und
`/EFI/ubuntu/shimx64.efi`. Das sind Beispiele, keine fertigen Werte für deinen iMac.
Eine Dateisystem-UUID ist nicht dasselbe wie PARTUUID. Beim Loader werden die
Backslashes aus `efibootmgr` durch `/` ersetzt.

## 3. Bootimage erstellen

Auf einem **x86_64-Linux-Rechner**, beispielsweise Ubuntu/Debian:

```sh
sudo apt install python3 gcc libc6-dev grub-efi-amd64-bin grub-common mtools dosfstools fdisk
python3 scripts/build-image.py \
  --internal-uuid ABCD-1234 \
  --internal-loader /EFI/ubuntu/shimx64.efi \
  --output build/imac-boot.img
```

Das Skript lädt einen festgelegten Stand von
[tinycore-tdm](https://github.com/frogro/tinycore-tdm), prüft dessen Bootdateien und
baut GRUB sowie eine zusätzliche TinyCore-Erweiterung für die Power-Taste.
Es erzeugt **eine 512-MiB-Imagedatei und eine JSON-Begleitdatei**. Es schreibt nicht
auf echte Laufwerke und überschreibt keine vorhandenen Ausgabedateien.

Optional `--ssh-key ~/.ssh/id_ed25519.pub` für TinyCore-Wartung ergänzen. SSH benötigt
weiterhin eine Netzwerkverbindung zum iMac; die Tastersteuerung selbst benötigt sie
nicht. Ohne diese Option bleibt SSH aus. `--source /pfad/tinycore-tdm` verwendet
statt Downloads einen vollständigen lokalen Checkout mit gültigem Manifest.

### Ohne interne HDD/SSD: zwei Monitor-Optionen

**Auf Tastendruck warten:** GRUB bleibt im Menü. Kurz drücken startet TinyCore/TDM.
Langes Drücken zeigt „Kein internes Linux eingerichtet“ und kehrt ins Menü zurück.

```sh
python3 scripts/build-image.py --tdm-only --output build/tdm-only.img
```

**Direkt als Monitor starten:** GRUB startet TinyCore ohne Menüwartezeit. TinyCore
aktiviert anschließend TDM; die normale Linux-Bootzeit und TDM-Startverzögerung bleiben.

```sh
python3 scripts/build-image.py --tdm-autostart --output build/tdm-autostart.img
```

Diese beiden Alternativen benötigen **kein internes Bootziel und keine zusätzliche
interne oder externe HDD/SSD**. Schritt 2 und die Einrichtung des internen Linux
in Schritt 6 entfallen. Pi, microSD und USB-Verbindung zum iMac werden weiterhin
benötigt. Im laufenden TinyCore fährt langes Drücken den iMac herunter.

Jeweils genau eine Option wählen; nicht mit `--internal-config`, `--internal-uuid`
oder `--internal-loader` kombinieren. `--source` und `--ssh-key` bleiben verfügbar.
Ohne diese Monitor-Optionen gilt weiterhin die Auswahl zwischen TDM und internem
Linux. Nach einem TinyCore-Bootfehler bleibt GRUB im Menü, auch bei Autostart.

## 4. Pi einrichten

Projekt sowie Image **und dessen gleichnamige `.json`-Datei** auf den Pi kopieren.
Auf dem Pi:

```sh
sudo apt install python3 network-manager
sudo python3 scripts/install-pi.py --image /pfad/imac-boot.img
```

Der Installer prüft das Pi-Modell, fragt nach einem neuen WLAN-Passwort, richtet
`iMac-TDM` als eigenes WLAN ein und installiert die USB-/Controller-Dienste.
Mit `--ssid MEIN-NAME` lässt sich der WLAN-Name ändern.

Danach mit `sudo raspi-config` das WLAN-Land setzen und den Pi neu starten.
**Die bisherige WLAN-Verbindung des Pi wird durch den Access Point ersetzt.**
Zur Einrichtung lokalen Zugriff oder eine zweite Verbindung bereithalten.

Ist der Taster bereits eingerichtet, übernimmt `--settings /pfad/button-settings.toml`
seine vorhandenen WLAN-Daten und den Token. Die Datei vertraulich übertragen;
der Taster muss dafür nicht neu eingerichtet werden:

```sh
sudo python3 scripts/install-pi.py --image /pfad/imac-boot.img --settings /pfad/button-settings.toml
```

Der Installer erzeugt `/etc/imac-tdm-controller/button-settings.toml` mit den
Zugangsdaten für den Taster. Diese Datei vertraulich auf den Einrichtungsrechner
kopieren. Der API-Schlüssel wird nicht auf der Konsole ausgegeben.

Die Dienste starten nach dem Neustart. Diagnose auf dem Pi:

```sh
systemctl status imac-tdm-gadget imac-tdm-controller
journalctl -u imac-tdm-controller -b
```

## 5. WLAN-Taster installieren

Der Installer fragt nach dem Board und zeigt **am Ende die richtigen GPIOs** an:

```sh
python3 scripts/install-button.py --settings /pfad/button-settings.toml
```

Ohne `--settings` werden WLAN-Name, Passwort, Pi-Adresse und Controller-Token
interaktiv abgefragt. Passwörter und Token werden verdeckt eingegeben.

- **Pico W:** Auf Wunsch wird die geprüfte CircuitPython-UF2 geladen. Pico mit
  gedrücktem BOOTSEL anschließen und sein `RPI-RP2`-Laufwerk auswählen. Nach dem
  Firmwarewechsel das neue `CIRCUITPY`-Laufwerk auswählen. Der Installer prüft die
  Boardkennung und kopiert Konfiguration und Tastercode mit Rückleseprüfung.
- **ESP32 DevKit v1, DevKitC V4 oder TinyPICO:** Installation über den ausgewählten seriellen
  USB-Port. Der Installer kann den Flash nach ausdrücklicher Bestätigung löschen,
  die passende CircuitPython-Firmware schreiben und die Tasterdateien über die
  serielle Konsole übertragen. Auch hier erfolgt eine Rückleseprüfung.

Für den ESP32 zuvor einmal die Werkzeuge in einer Python-Umgebung installieren:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install 'esptool>=5,<6' pyserial
python3 scripts/install-button.py --settings /pfad/button-settings.toml
```

CircuitPython ist auf allen unterstützten Boards derselbe **Programmcode**, aber die Firmware
ist jeweils boardspezifisch. Bestehende Board-Dateien vor Neuinstallation sichern.
Der Installer fragt vor Firmware- und Dateischreibzugriffen nach Bestätigung.
Bei seriellen Zugriffsproblemen Portberechtigungen prüfen und andere Serial-Monitore
schließen. Es werden weder private SSH-Schlüssel noch WLAN-Daten ins Git-Repo kopiert.

Nur vorbereiten, ohne Board-Zugriff:

```sh
python3 scripts/install-button.py --settings /pfad/button-settings.toml \
  --prepare-only build/taster
```

### Taster anschließen

| Board | Erster Tasterkontakt | Zweiter Tasterkontakt |
| --- | --- | --- |
| Pico W | GP15, physischer Pin 20 | GND, physischer Pin 18 |
| ESP32 DevKit v1 / WROOM-32 | Beschriftung GPIO4/IO4 | Beschriftung GND |
| ESP32-DevKitC V4 / WROOM-32E | GPIO4/IO4, J3 Pin 13 | GND, J3 Pin 1 |
| TinyPICO V3 USB-C | Beschriftung 25 / GPIO25 | Beschriftung GND |

Der Installer setzt den passenden CircuitPython-Pinnamen automatisch: `GP15`
beim Pico W, `D4` beim ESP32 DevKit v1 und `IO4` beim DevKitC V4. Beide ESP32-Namen
bezeichnen GPIO4. Beim TinyPICO setzt er `IO25` für GPIO25.

Der Taster verbindet beim Drücken **GPIO mit Masse**. Ein interner Pull-up wird
aktiviert; kein externer Widerstand nötig. Nicht an 5 V oder 3,3 V anschließen.
Bei vierbeinigen Tastern auf die intern verbundenen Beinpaare achten.

Pinquellen: [Pico-W-Datenblatt](https://datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf),
[ESP32-DevKitC V4](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html#header-block).

### TinyPICO mit Akku

Für den WLAN-Taster reichen TinyPICO, ein Taster zwischen **25 und GND** sowie ein
**geschützter 1S-LiPo-Akku mit 3,7 V Nennspannung (maximal 4,2 V)** am JST-Anschluss.
Die Polarität muss zur Markierung **+ und −** auf der Platine passen. Falls der
JST-Anschluss lose beiliegt, muss er zuerst eingelötet werden.
Ein USB-C-Datenkabel wird zum Einrichten und Laden benötigt. Die Ladeelektronik
ist bereits auf dem Board; ein zusätzliches Ladegerät-Modul oder Tasterwiderstand
ist nicht nötig. Der Pi bleibt als Gegenstelle erforderlich.

Die Firmware hält WLAN momentan dauerhaft verbunden und nutzt keinen Tiefschlaf.
Die Akkulaufzeit ist noch nicht am Gerät gemessen. Die RGB-LED wird nicht als
Statusanzeige angesteuert.

Quellen: [Akku und Laden beim Hersteller](https://help.unexpectedmaker.com/docs/power/battery-power/),
[TinyPICO-Firmware](https://circuitpython.org/board/unexpectedmaker_tinypico/),
[GPIO25 in CircuitPython](https://github.com/adafruit/circuitpython/blob/10.3.1/ports/espressif/boards/unexpectedmaker_tinypico/pins.c).

## 6. Power-Taste im internen Linux aktivieren

Auf dem **iMac im internen Linux**, nicht auf dem Pi:

```sh
sudo sh linux/install-power-key.sh --apply
```

Diese Einrichtung setzt bei systemd-logind die Power-Taste auf normales
Herunterfahren und ergänzt die Geräteerkennung. Sie installiert keinen eigenen
Empfangsdienst. Danach Linux neu starten. In einer grafischen Oberfläche kann
zusätzlich deren Energieverwaltung die Power-Taste übernehmen: Dort ebenfalls
**Herunterfahren** einstellen. Offene Dokumente oder Anwendungen können weiterhin
Rückfragen auslösen; Programme werden nicht zwangsweise beendet.

TinyCore bekommt seinen kleinen Power-Tasten-Empfänger bereits im Bootimage.
Er behandelt ausschließlich das USB-Eingabegerät dieses Controllers. „Zur internen
Anzeige zurück“ ist keine Aktion des WLAN-Tasters.

## 7. Am iMac verwenden

1. Pi starten und warten, bis sein WLAN und USB-Gerät verfügbar sind.
2. Beim iMac zunächst mit Alt/Option das USB-EFI-Bootmedium wählen.
3. Standard: GRUB wartet unbegrenzt; kurz für TDM, lange für internes Linux.
   Mit `--tdm-only` gibt es kein internes Bootziel; mit `--tdm-autostart` entfällt
   die Menüwartezeit.
4. Im laufenden System löst erneutes langes Drücken die HID-Power-Taste aus.

Zum ersten Test kann eine normale Tastatur im GRUB-Menü `T` oder `L` senden.
Als dauerhafter Einstieg muss der USB-EFI-Loader in der iMac-Firmware eingerichtet
werden. Das wird **nicht ungeprüft vom Installer am Einrichtungsrechner verändert**.
GRUB ändert beim Start des internen Linux keine NVRAM-Bootreihenfolge und speichert
keine letzte Menüauswahl. Das reale Firmwareverhalten und der Start ohne Pi gehören
zum Test am iMac. Einschalten eines vollständig ausgeschalteten iMac ist nicht Teil
von Version 1; dafür bleibt zunächst dessen physischer Einschaltknopf.

## Technischer Stand

GRUB schreibt `menu`, `tinycore` oder `linux` in einen vorab angelegten
Statusbereich des Images. Der Pi liest diesen Bereich, ohne das Dateisystem zu
mounten. Nur der iMac darf das exportierte Image verändern. Die Markierung sagt,
welcher Startweg ausgewählt wurde, **nicht**, ob Linux bereits fertig gestartet ist
oder der Bildschirm tatsächlich TDM zeigt. Unbekannte/ungültige Zustände führen zu
keiner Tastenausgabe. Vor Änderungen am Image beide Pi-Dienste stoppen.

Die HTTP-Steuerung ist an die AP-Adresse gebunden, verlangt einen zufälligen Token
und verwendet kurzlebige Einmaltickets gegen doppelte/verzögerte Aktionen. Die
Übertragung erfolgt innerhalb des WPA2-WLANs; kein Portforwarding ins Internet
einrichten. Der Linux-Foundation-USB-Beispiel-VID/PID ist für diesen privaten
Prototyp vorgesehen, keine zugeteilte Produktkennung.

[Architektur](docs/architecture.md) · [Tests](docs/testing.md) ·
[Quellen und Lizenzen](docs/sources.md)

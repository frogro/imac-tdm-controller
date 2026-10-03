# Architektur und Zustände

Der Controller wird durch zwei systemd-Dienste auf dem Pi gestartet. `gadget`
erstellt per configfs ein USB-Composite-Gerät mit Massenspeicher, Boot-Tastatur
und einer separaten HID-System-Control-Funktion (System Power Down). Der
HTTP-Controller sendet Berichte an genau die zugehörigen `/dev/hidg*`-Geräte.

Die Tastatur sendet in GRUB `t` beziehungsweise `l`. Im ausgewählten
Betriebssystem sendet nur ein langer Tastendruck ein Power-Ereignis, gefolgt von
einem Release. Der Pi führt selbst **niemals einen Poweroff-Befehl** aus.

## Status aus GRUB

`STATE.ENV` ist ein 1024-Byte-GRUB-Environmentblock im FAT32-Dateisystem. Der
Builder prüft seine zusammenhängende Lage und speichert den absoluten Offset
in der Image-Begleitdatei. GRUB setzt `phase=menu` beim Einstieg und vor der
Übergabe `phase=tinycore` oder `phase=linux`. Bei fehlendem internen Loader bleibt
beziehungsweise wird der Zustand `menu`.

Der Pi liest den Block zweimal per `pread`, prüft Header, Größe und eindeutige
Werte. Er mountet das Image nicht und schreibt nicht hinein. Aktiver USB-Host
und Pi dürfen das Dateisystem nicht gleichzeitig verändern. Ein defragmentiertes,
neu formatiertes oder manuell umgebautes Image benötigt neu ermittelte Metadaten.

Diese Methode wurde in QEMU auf FAT32/UEFI erprobt; am Apple-EFI und Linux
Mass-Storage-Gadget steht der gemeinsame Hardwaretest aus. Ein veralteter gültiger
Block ist keine gesicherte Laufzeitmeldung: besonders Dienstneustart, USB-Reset,
Suspend und Bootfehler müssen am Gerät geprüft werden. Die UDC-Verbindung muss
`configured` sein, sonst wird kein Befehl gesendet. Nach einer Menüaktion gilt
eine 20-Sekunden-Sperre; sie ersetzt keine Betriebssystem-Bereitschaftsmeldung.

## WLAN-Taster

Ein normal offener Taster gegen Masse nutzt einen internen Pull-up. Die Firmware
entprellt 40 ms, löst kurz beim Loslassen und lang ab drei Sekunden einmalig aus.
Beim Einschalten beziehungsweise Wiederverbinden muss der Taster zunächst
losgelassen werden. Es gibt keine Offline-Warteschlange.

Ein Ereignis holt authentifiziert ein fünf Sekunden gültiges Ticket. Das Ticket
ist an die beobachtete Phase gebunden und wird vor dem HID-Schreibzugriff verbraucht.
Wiederholte Requests mit demselben Ticket wiederholen die Aktion nicht. Ein Fehler
beim HID-Schreiben wird nicht automatisch erneut ausgeführt. Die Firmware benötigt
keine externen CircuitPython-Bibliotheken; `wifi` und `socketpool` müssen im
gewählten Board-Build vorhanden sein.

## Abschalten

Das interne Linux verwendet seine Energieverwaltung. Der Installer konfiguriert
systemd-logind und udev, ohne eigenen Dauerdienst. Desktop-Power-Manager können die
Taste übernehmen; deren Einstellung gehört zum Test.

TinyCore hat keinen systemd-logind. Ein statisch gebautes x86_64-Programm liest nur
Input-Geräte mit passender USB-Kennung und Produktname. Bei `KEY_POWER`, Wert 1,
ruft es `/sbin/poweroff` auf. Ein vorhandenes Linux-Input-Gerät allein ist keine
Freigabe: Geräte-ID und Name müssen passen. Es gibt keinen allgemeinen
Shell-Befehlsparser und keinen Ausschalt-Netzwerkdienst im iMac.

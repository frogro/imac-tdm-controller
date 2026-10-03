#!/bin/sh
# Run once on the INTERNAL Linux installation, not on the Pi/build host.
set -eu
if [ "${1:-}" != '--apply' ]; then
  echo 'Interner Linux-iMac: sudo sh linux/install-power-key.sh --apply'
  echo 'Konfiguriert systemd-logind für die HID-Power-Taste. Wirksam nach Neustart.'
  echo 'Bei Desktop-Sitzungen zusätzlich deren Ein-/Ausschalter-Aktion auf Herunterfahren setzen.'
  exit 0
fi
[ "$(id -u)" -eq 0 ] || { echo 'Bitte mit sudo ausführen.' >&2; exit 1; }
[ -d /run/systemd/system ] || { echo 'Dieses Setup benötigt systemd-logind.' >&2; exit 1; }
mkdir -p /etc/systemd/logind.conf.d /etc/udev/rules.d
CONFIG=/etc/systemd/logind.conf.d/90-imac-tdm-power.conf
RULE=/etc/udev/rules.d/90-imac-tdm-power.rules
[ ! -e "$CONFIG" ] && [ ! -e "$RULE" ] || { echo 'Projektkonfiguration existiert bereits.' >&2; exit 1; }
cat > "$CONFIG" <<'EOF'
[Login]
HandlePowerKey=poweroff
PowerKeyIgnoreInhibited=no
EOF
# Tag the System Control input device for logind, including minimal installations.
cat > "$RULE" <<'EOF'
ACTION=="add", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="1d6b", ATTRS{idProduct}=="0104", ATTRS{product}=="iMac TDM Controller", TAG+="power-switch"
EOF
udevadm control --reload-rules
echo 'Installiert. Linux neu starten, bevor die Power-Taste getestet wird.'
echo 'Desktop-Energieverwaltung kann logind übersteuern. Keine Prozesse zwangsweise beendet.'

#!/bin/sh
# Additional initramfs: preserve the upstream bootlocal and run the power handler.
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/usr/sbin:/bin:/usr/bin
export PATH
modprobe usbhid 2>/dev/null || true
modprobe evdev 2>/dev/null || true
/usr/local/sbin/tdm-power-listener >> /var/log/tdm-power.log 2>&1 &
exec /opt/tdm-upstream-bootlocal.sh

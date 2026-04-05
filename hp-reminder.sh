#!/bin/bash
while true; do
    HOUR=$(date +%H)
    if [ "$HOUR" -ge 8 ] && [ "$HOUR" -lt 17 ]; then
        notify-send -u critical "CALL HP SUPPORT NOW" "Serial: CND24534YK | Phone: 1-800-474-6836 | Ask for BIOS admin password reset | Model: ZBook Fury 15 G8 | Kill: pkill -f hp-reminder"
    fi
    sleep 1800
done

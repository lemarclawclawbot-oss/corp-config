#!/bin/bash
# Remind Lemar to enable WoL in BIOS every 15 minutes
# Kill this script once BIOS is done: pkill -f bios-reminder

while true; do
    notify-send -u critical "BIOS REMINDER" "Enable Wake-on-LAN!\nReboot → F10 → Advanced → Built-in Device Options → Enable 'Wake on LAN'\n\nKill this reminder: pkill -f bios-reminder"
    sleep 900
done

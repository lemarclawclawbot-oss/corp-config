#!/bin/bash
# Wake-on-LAN Setup for ZBook
# Run this WITH sudo: sudo bash setup-wol.sh
#
# ALSO REQUIRED: Enable WoL in BIOS
#   1. Reboot → press F10 for BIOS Setup
#   2. Advanced → Built-in Device Options
#   3. Enable "Wake on LAN" or "S5 Wake on LAN"
#   4. Save and exit

set -e

IFACE="enp0s31f6"

echo "=== Wake-on-LAN Setup for ZBook ==="
echo ""

# Check current WoL status
echo "1. Current WoL status:"
ethtool "$IFACE" | grep -i wake
echo ""

# Enable WoL (g = magic packet)
echo "2. Enabling WoL on $IFACE..."
ethtool -s "$IFACE" wol g
echo "   Done. Verifying:"
ethtool "$IFACE" | grep -i wake
echo ""

# Make it persistent across reboots via systemd
echo "3. Creating systemd service for persistence..."
cat > /etc/systemd/system/wol-enable.service << 'UNIT'
[Unit]
Description=Enable Wake-on-LAN
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s enp0s31f6 wol g
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable wol-enable.service
systemctl start wol-enable.service
echo "   Service created and enabled."
echo ""

echo "=== WoL Setup Complete ==="
echo ""
echo "ZBook MAC: 38:ca:84:c7:56:2c"
echo "To wake ZBook from another machine:"
echo "  Option 1: python3 -c \"import observer; observer.send_wol('38:ca:84:c7:56:2c')\""
echo "  Option 2: wakeonlan 38:ca:84:c7:56:2c"
echo "  Option 3: sudo apt install wakeonlan && wakeonlan 38:ca:84:c7:56:2c"
echo ""
echo "IMPORTANT: You must also enable WoL in BIOS (F10 at boot → Advanced → Built-in Device Options)"

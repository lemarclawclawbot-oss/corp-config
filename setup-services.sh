#!/bin/bash
# Setup systemd services for Corp Fleet
# Run with sudo: sudo bash setup-services.sh
# Auto-detects machine role

set -e

CORP_DIR="$HOME/corp-config"
if [ "$SUDO_USER" ]; then
    CORP_DIR="/home/$SUDO_USER/corp-config"
    RUN_USER="$SUDO_USER"
else
    RUN_USER="$USER"
fi

HOSTNAME=$(hostname | tr '[:upper:]' '[:lower:]')

echo "=== Corp Fleet Service Setup ==="
echo "User: $RUN_USER"
echo "Corp dir: $CORP_DIR"

# Detect role
if echo "$HOSTNAME" | grep -qi "zbook\|hp"; then
    ROLE="zbook"
elif echo "$HOSTNAME" | grep -qi "lenovo"; then
    ROLE="lenovo"
else
    ROLE="chromebook"
fi
echo "Detected role: $ROLE"
echo ""

# Observer service (all machines)
echo "1. Creating observer service..."
cat > /etc/systemd/system/corp-observer.service << UNIT
[Unit]
Description=Corp Fleet Observer ($ROLE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$CORP_DIR
ExecStart=/usr/bin/python3 $CORP_DIR/observer.py --role $ROLE
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable corp-observer.service
systemctl start corp-observer.service
echo "   Observer service started."

# Dashboard service (ZBook only)
if [ "$ROLE" = "zbook" ]; then
    echo "2. Creating dashboard service..."
    cat > /etc/systemd/system/corp-dashboard.service << UNIT
[Unit]
Description=Corp Mission Control Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$CORP_DIR/dashboard
ExecStart=/usr/bin/python3 $CORP_DIR/dashboard/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable corp-dashboard.service
    systemctl start corp-dashboard.service
    echo "   Dashboard service started on port 5000."
    echo "   Access: http://$(hostname -I | awk '{print $1}'):5000"
fi

echo ""
echo "=== Services Setup Complete ==="
echo "Check status: systemctl status corp-observer corp-dashboard"

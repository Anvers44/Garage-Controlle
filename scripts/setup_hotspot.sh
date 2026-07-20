#!/usr/bin/env bash
#
# Configure et démarre un hotspot Wi-Fi sur wlan0.
# Nécessite d'être lancé en root (appelé depuis install.sh).
#
set -euo pipefail

SSID="GarageControl"
PASSWORD="garage1234"   # <-- Changez ce mot de passe !
IFACE="wlan0"
IP="192.168.4.1"

echo "==> Installation de hostapd et dnsmasq"
apt-get install -y hostapd dnsmasq

# Débloquer le Wi-Fi (nécessaire sur Pi Zero / Pi 3 / Pi 4)
rfkill unblock wifi

# Arrêter wpa_supplicant sur cette interface (pas de réseau externe)
systemctl stop wpa_supplicant || true

# Empêcher NetworkManager de gérer wlan0 (utilisé par hostapd)
if command -v nmcli &>/dev/null; then
    nmcli device set "${IFACE}" managed no || true
fi

# Configuration hostapd
cat > /etc/hostapd/hostapd.conf <<EOF
interface=${IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=6
wmm_enabled=1
macaddr_acl=0
auth_algs=1
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# Configuration dnsmasq (DHCP + résolution DNS vers le Pi)
cat > /etc/dnsmasq.conf <<EOF
interface=${IFACE}
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
address=/#/${IP}
EOF

# Appliquer l'IP immédiatement sans reboot
ip addr flush dev "${IFACE}" 2>/dev/null || true
ip addr add "${IP}/24" dev "${IFACE}"
ip link set "${IFACE}" up

systemctl unmask hostapd
systemctl enable hostapd dnsmasq
systemctl restart hostapd dnsmasq

echo "==> Hotspot actif !"
echo "    SSID     : ${SSID}"
echo "    Password : ${PASSWORD}"
echo "    IP Pi    : ${IP}"
echo "    Interface: http://${IP}:8080"

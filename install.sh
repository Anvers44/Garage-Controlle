#!/usr/bin/env bash
#
# Installation du Garage Controller GSM sur Raspberry Pi OS.
#
# - crée un environnement virtuel Python et installe les dépendances ;
# - installe et active le service systemd (backend GSM + interface web) ;
# - ajoute l'utilisateur au groupe 'dialout' (accès /dev/serial0).
#
# Usage :
#   sudo ./install.sh
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="garage-controller"
SERVICE_SRC="${APP_DIR}/systemd/${SERVICE_NAME}.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

# Utilisateur cible : celui qui a lancé sudo, sinon l'utilisateur courant.
TARGET_USER="${SUDO_USER:-$(id -un)}"

echo "==> Garage Controller GSM — installation"
echo "    Dossier applicatif : ${APP_DIR}"
echo "    Utilisateur cible  : ${TARGET_USER}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ce script doit être lancé avec sudo (installation systemd)." >&2
  exit 1
fi

echo "==> Installation des paquets système (python3-venv, python3-pip)"
apt-get update -qq
apt-get install -y python3-venv python3-pip

echo "==> Création de l'environnement virtuel"
sudo -u "${TARGET_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${TARGET_USER}" "${APP_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${TARGET_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> Accès au port série (groupe dialout)"
usermod -aG dialout "${TARGET_USER}" || true

echo "==> Installation du service systemd"
sed -e "s#__APP_DIR__#${APP_DIR}#g" \
    -e "s#__USER__#${TARGET_USER}#g" \
    "${SERVICE_SRC}" > "${SERVICE_DST}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "==> Terminé."
echo "    Statut  : systemctl status ${SERVICE_NAME}"
echo "    Logs    : journalctl -u ${SERVICE_NAME} -f"
echo "    Web     : http://<ip-du-pi>:8080  (login: admin / admin — à changer)"

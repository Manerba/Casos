#!/bin/bash
#
# Tareas - Einzeiler-Installation
#
# Verwendung: curl -s http://188.245.43.207/tareas/install.sh | bash
#

set -e

REPO_SERVER="188.245.43.207"
REPO_URL="http://$REPO_SERVER/tareas/repo"
GPG_KEY_URL="$REPO_URL/tareas-repo.gpg"
KEYRING_PATH="/etc/apt/keyrings/tareas-repo.gpg"
SOURCES_LIST="/etc/apt/sources.list.d/tareas.list"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
error() { echo -e "${RED}[FEHLER]${NC} $1"; exit 1; }

# Root-Check
if [ "$(id -u)" -ne 0 ]; then
    error "Dieses Script muss als root ausgefuehrt werden."
fi

# Ubuntu 24.04 Check
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$ID" != "ubuntu" ] || [[ "$VERSION_ID" != "24.04"* ]]; then
        error "Ubuntu 24.04 erforderlich. Gefunden: $ID $VERSION_ID"
    fi
else
    error "Konnte Betriebssystem nicht erkennen."
fi

info "Installiere Tareas auf Ubuntu 24.04..."

# GPG-Key herunterladen
info "Lade GPG-Key herunter..."
mkdir -p /etc/apt/keyrings
curl -fsSL "$GPG_KEY_URL" -o "$KEYRING_PATH"

# APT-Quelle hinzufuegen
info "Fuege APT-Quelle hinzu..."
echo "deb [signed-by=$KEYRING_PATH] $REPO_URL noble main" > "$SOURCES_LIST"

# Paket installieren
info "Aktualisiere Paketlisten..."
apt-get update -qq

info "Installiere Tareas..."
apt-get install -y tareas

echo ""
info "=== Tareas erfolgreich installiert ==="
info "  App:   http://$(hostname -I | awk '{print $1}'):8504/"
info "  Admin: http://$(hostname -I | awk '{print $1}'):8505/"
info "  Login: admin / admin"
echo ""
info "Updates: apt update && apt upgrade tareas"
echo ""

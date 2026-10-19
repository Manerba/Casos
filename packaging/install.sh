#!/bin/bash
#
# Casos - Einzeiler-Installation
#
# Verwendung: curl -s http://188.245.43.207/casos/install.sh | bash
#

set -e

REPO_SERVER="188.245.43.207"
REPO_URL="http://$REPO_SERVER/casos/repo"
GPG_KEY_URL="$REPO_URL/casos-repo.gpg"
KEYRING_PATH="/etc/apt/keyrings/casos-repo.gpg"
SOURCES_LIST="/etc/apt/sources.list.d/casos.list"

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

info "Installiere Casos auf Ubuntu 24.04..."

# GPG-Key herunterladen (falls Armor-Format: automatisch konvertieren)
info "Lade GPG-Key herunter..."
mkdir -p /etc/apt/keyrings
curl -fsSL "$GPG_KEY_URL" -o /tmp/casos-repo-key.tmp
if file /tmp/casos-repo-key.tmp | grep -q "PGP public key"; then
    cp /tmp/casos-repo-key.tmp "$KEYRING_PATH"
else
    gpg --dearmor -o "$KEYRING_PATH" /tmp/casos-repo-key.tmp
fi
rm -f /tmp/casos-repo-key.tmp

# APT-Quelle hinzufuegen
info "Fuege APT-Quelle hinzu..."
echo "deb [signed-by=$KEYRING_PATH] $REPO_URL noble main" > "$SOURCES_LIST"

# Paket installieren
info "Aktualisiere Paketlisten..."
apt-get update -qq

info "Installiere Casos..."
apt-get install -y casos

echo ""
info "=== Casos erfolgreich installiert ==="
info "  App:   http://$(hostname -I | awk '{print $1}'):8514/"
info "  Admin: http://$(hostname -I | awk '{print $1}'):8515/"
info "  MCP:   http://$(hostname -I | awk '{print $1}'):8516/mcp/ (auch weiter auf Port 8514)"
info "  Login: admin / admin"
echo ""
info "Updates: apt update && apt upgrade casos"
echo ""

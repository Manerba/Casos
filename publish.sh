#!/bin/bash
#
# publish.sh - Tareas .deb-Paket bauen und auf Repo-Server veroeffentlichen
#
# Verwendung:
#   ./publish.sh          Paket bauen und veroeffentlichen
#   ./publish.sh --setup  Repo-Server erstmalig einrichten
#   ./publish.sh --build  Nur lokal bauen, nicht hochladen
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/version.txt"
REPO_SERVER="188.245.43.207"
REPO_BASE="/var/www/tareas"
REPO_DIR="$REPO_BASE/repo"
REPO_URL="http://$REPO_SERVER/tareas/repo"
GPG_KEY="C818D9020A2F43CEBCE2E7E0BA3D049F6600D868"
BUILD_DIR="/tmp/tareas-build"

# Farben
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[FEHLER]${NC} $1"; exit 1; }

# --------------------------------------------------------------------------
# Repo-Server erstmalig einrichten
# --------------------------------------------------------------------------
setup_server() {
    info "Richte Repo-Server ein ($REPO_SERVER)..."

    ssh root@$REPO_SERVER bash <<'REMOTE_SETUP'
set -e

REPO_BASE="/var/www/tareas"
REPO_DIR="$REPO_BASE/repo"

# Verzeichnisstruktur anlegen
mkdir -p "$REPO_DIR/dists/noble/main/binary-all"
mkdir -p "$REPO_DIR/pool/main/t/tareas"

# GPG Public Key exportieren
gpg --export --armor C818D9020A2F43CEBCE2E7E0BA3D049F6600D868 > "$REPO_DIR/tareas-repo.gpg"
echo "GPG-Key exportiert nach $REPO_DIR/tareas-repo.gpg"

# Apache-Config erstellen
cat > /etc/apache2/conf-available/tareas-repo.conf <<'APACHE_CONF'
# Tareas APT-Repository und Bootstrap-Script
Alias /tareas /var/www/tareas

<Directory /var/www/tareas>
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>

<Directory /var/www/tareas/repo>
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
APACHE_CONF

# Apache-Config aktivieren
a2enconf tareas-repo
systemctl reload apache2

echo "Apache-Config aktiviert und Apache neu geladen."
echo "Repo-Server Setup abgeschlossen."
REMOTE_SETUP

    info "Server-Setup abgeschlossen."
}

# --------------------------------------------------------------------------
# Version lesen
# --------------------------------------------------------------------------
read_version() {
    if [ ! -f "$VERSION_FILE" ]; then
        error "version.txt nicht gefunden!"
    fi
    VERSION=$(cat "$VERSION_FILE" | tr -d '\n')
    # Fuer .deb: + durch ~ ersetzen (dpkg-kompatibles Format)
    DEB_VERSION=$(echo "$VERSION" | sed 's/+/~/')
    PACKAGE_NAME="tareas_${DEB_VERSION}_all"
    info "Version: $VERSION (deb: $DEB_VERSION)"
}

# --------------------------------------------------------------------------
# .deb-Paket bauen
# --------------------------------------------------------------------------
build_package() {
    info "Baue .deb-Paket..."

    # Altes Build-Verzeichnis aufraeumen
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR/$PACKAGE_NAME/DEBIAN"
    mkdir -p "$BUILD_DIR/$PACKAGE_NAME/opt/tareas"

    PKG_ROOT="$BUILD_DIR/$PACKAGE_NAME"

    # --- DEBIAN-Dateien ---
    # control mit Version einsetzen
    sed "s/__VERSION__/$DEB_VERSION/" "$SCRIPT_DIR/packaging/DEBIAN/control" > "$PKG_ROOT/DEBIAN/control"

    # Scripts kopieren
    cp "$SCRIPT_DIR/packaging/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/postinst"
    cp "$SCRIPT_DIR/packaging/DEBIAN/prerm"    "$PKG_ROOT/DEBIAN/prerm"
    cp "$SCRIPT_DIR/packaging/DEBIAN/postrm"   "$PKG_ROOT/DEBIAN/postrm"
    chmod 755 "$PKG_ROOT/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/prerm" "$PKG_ROOT/DEBIAN/postrm"
    chmod 644 "$PKG_ROOT/DEBIAN/control"
    chmod 755 "$PKG_ROOT/DEBIAN"

    # --- Projektdateien kopieren ---
    APP_DIR="$PKG_ROOT/opt/tareas"

    # dashboard/ (Backend, Templates, Static)
    rsync -a --exclude='__pycache__' "$SCRIPT_DIR/dashboard/" "$APP_DIR/dashboard/"

    # scripts/ (Original-Dateien kopieren, dann mit Paket-Versionen ueberschreiben)
    rsync -a --exclude='__pycache__' "$SCRIPT_DIR/scripts/" "$APP_DIR/scripts/"
    cp "$SCRIPT_DIR/packaging/services/"* "$APP_DIR/scripts/"

    # Einzeldateien
    cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"
    cp "$SCRIPT_DIR/version.txt"      "$APP_DIR/"

    # --- Paket bauen ---
    DEB_FILE="$BUILD_DIR/${PACKAGE_NAME}.deb"
    dpkg-deb --build "$PKG_ROOT" "$DEB_FILE"

    info "Paket erstellt: $DEB_FILE"
    dpkg-deb --info "$DEB_FILE"
    echo ""
}

# --------------------------------------------------------------------------
# install.sh auf Server hochladen
# --------------------------------------------------------------------------
upload_install_script() {
    info "Lade install.sh auf Server..."
    scp "$SCRIPT_DIR/packaging/install.sh" root@$REPO_SERVER:$REPO_BASE/install.sh
    ssh root@$REPO_SERVER "chmod 644 $REPO_BASE/install.sh"
}

# --------------------------------------------------------------------------
# Paket auf Repo-Server hochladen und Index aktualisieren
# --------------------------------------------------------------------------
publish_package() {
    DEB_FILE="$BUILD_DIR/${PACKAGE_NAME}.deb"

    if [ ! -f "$DEB_FILE" ]; then
        error ".deb-Datei nicht gefunden: $DEB_FILE"
    fi

    info "Lade Paket auf $REPO_SERVER..."
    scp "$DEB_FILE" root@$REPO_SERVER:$REPO_DIR/pool/main/t/tareas/

    info "Aktualisiere Repository-Index..."
    ssh root@$REPO_SERVER bash <<REMOTE_INDEX
set -e

REPO_DIR="$REPO_DIR"
GPG_KEY="$GPG_KEY"

cd "\$REPO_DIR"

# Packages-Index generieren
dpkg-scanpackages --arch all pool/ > dists/noble/main/binary-all/Packages
gzip -k -f dists/noble/main/binary-all/Packages

# Release-Datei generieren
cd dists/noble
cat > Release <<EOF_RELEASE
Origin: Tareas
Label: Tareas
Suite: noble
Codename: noble
Architectures: all
Components: main
Description: Tareas APT Repository
EOF_RELEASE

# Hashes berechnen und anhaengen
echo "MD5Sum:" >> Release
for f in main/binary-all/Packages main/binary-all/Packages.gz; do
    if [ -f "\$f" ]; then
        SIZE=\$(stat -c%s "\$f")
        MD5=\$(md5sum "\$f" | awk '{print \$1}')
        echo " \$MD5 \$SIZE \$f" >> Release
    fi
done

echo "SHA256:" >> Release
for f in main/binary-all/Packages main/binary-all/Packages.gz; do
    if [ -f "\$f" ]; then
        SIZE=\$(stat -c%s "\$f")
        SHA=\$(sha256sum "\$f" | awk '{print \$1}')
        echo " \$SHA \$SIZE \$f" >> Release
    fi
done

# GPG-Signierung
rm -f Release.gpg InRelease
gpg --default-key "\$GPG_KEY" --armor --detach-sign --output Release.gpg Release
gpg --default-key "\$GPG_KEY" --armor --clearsign --output InRelease Release

echo "Repository-Index aktualisiert und signiert."
REMOTE_INDEX

    info "Repository aktualisiert."
}

# --------------------------------------------------------------------------
# Hauptprogramm
# --------------------------------------------------------------------------
case "${1:-}" in
    --setup)
        setup_server
        ;;
    --build)
        read_version
        build_package
        info "Nur lokal gebaut (--build). Kein Upload."
        ;;
    *)
        read_version
        build_package
        upload_install_script
        publish_package
        echo ""
        info "=== Veroeffentlichung erfolgreich ==="
        info "Version: $VERSION"
        info "Repo:    $REPO_URL"
        info "Install: curl -s http://$REPO_SERVER/tareas/install.sh | bash"
        echo ""
        ;;
esac

# Build-Verzeichnis aufraeumen
rm -rf "$BUILD_DIR"

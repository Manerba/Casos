#!/bin/bash
#
# publish.sh - Casos .deb-Paket bauen und auf Repo-Server veroeffentlichen
#              + GitHub-Sync fuer Open-Source-Veroeffentlichung
#
# Verwendung:
#   ./publish.sh              Paket bauen und veroeffentlichen
#   ./publish.sh --setup      Repo-Server erstmalig einrichten
#   ./publish.sh --build      Nur lokal bauen, nicht hochladen
#   ./publish.sh --github-init  GitHub-Repo erstellen + Initial-Commit
#   ./publish.sh --github       Inkrementeller Sync zu GitHub
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/version.txt"
REPO_SERVER="188.245.43.207"
REPO_BASE="/var/www/casos"
REPO_DIR="$REPO_BASE/repo"
REPO_URL="http://$REPO_SERVER/casos/repo"
GPG_KEY="C818D9020A2F43CEBCE2E7E0BA3D049F6600D868"
BUILD_DIR="/tmp/casos-build"
GITHUB_REPO="Manerba/casos"
GITHUB_DIR="/tmp/casos-github"

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

REPO_BASE="/var/www/casos"
REPO_DIR="$REPO_BASE/repo"

# Verzeichnisstruktur anlegen
mkdir -p "$REPO_DIR/dists/noble/main/binary-all"
mkdir -p "$REPO_DIR/pool/main/c/casos"

# GPG Public Key exportieren
gpg --export C818D9020A2F43CEBCE2E7E0BA3D049F6600D868 > "$REPO_DIR/casos-repo.gpg"
echo "GPG-Key exportiert nach $REPO_DIR/casos-repo.gpg"

# Apache-Config erstellen
cat > /etc/apache2/conf-available/casos-repo.conf <<'APACHE_CONF'
# Casos APT-Repository und Bootstrap-Script
Alias /casos /var/www/casos

<Directory /var/www/casos>
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>

<Directory /var/www/casos/repo>
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
APACHE_CONF

# Apache-Config aktivieren
a2enconf casos-repo
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
    PACKAGE_NAME="casos_${DEB_VERSION}_all"
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
    mkdir -p "$BUILD_DIR/$PACKAGE_NAME/opt/casos"

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
    APP_DIR="$PKG_ROOT/opt/casos"

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
    scp "$DEB_FILE" root@$REPO_SERVER:$REPO_DIR/pool/main/c/casos/

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
Origin: Casos
Label: Casos
Suite: noble
Codename: noble
Architectures: all
Components: main
Description: Casos APT Repository
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
# Bereinigte Kopie erstellen (fuer .deb und GitHub)
# --------------------------------------------------------------------------
prepare_clean_copy() {
    local TARGET_DIR="$1"

    info "Erstelle bereinigte Kopie in $TARGET_DIR..."

    rm -rf "$TARGET_DIR"
    mkdir -p "$TARGET_DIR"

    # Exclusions deckungsgleich mit .gitignore plus publish-spezifische Ausschluesse.
    # WICHTIG: wenn ein neuer Eintrag in .gitignore landet, hier ergaenzen
    # (oder den --exclude-from-Block unten dafuer nutzen).
    rsync -a \
        --exclude-from="$SCRIPT_DIR/.gitignore" \
        --exclude='.git/' \
        --exclude='.gitattributes' \
        --exclude='data/' \
        "$SCRIPT_DIR/" "$TARGET_DIR/"

    # Production-Service-Dateien ueber Dev-Versionen kopieren
    if [ -d "$SCRIPT_DIR/packaging/services/" ]; then
        cp "$SCRIPT_DIR/packaging/services/"* "$TARGET_DIR/scripts/"
    fi

    # Interne Dateien/Skripte entfernen (publish.sh + Helpers gehoeren nicht ins
    # oeffentliche Repo)
    rm -f  "$TARGET_DIR/publish.sh"
    rm -f  "$TARGET_DIR/git-commit.sh"
    rm -f  "$TARGET_DIR/AGENTS.md"
    rm -f  "$TARGET_DIR/docs/prompts.txt"
    rm -rf "$TARGET_DIR/docs/TODO/"
    rm -rf "$TARGET_DIR/packaging/"

    info "Bereinigte Kopie erstellt."
}

# --------------------------------------------------------------------------
# GitHub: Erstmaliges Setup (Repo erstellen + Initial-Commit)
# --------------------------------------------------------------------------
github_init() {
    read_version

    info "Erstelle GitHub-Repository $GITHUB_REPO..."

    # Repo auf GitHub erstellen (falls nicht vorhanden)
    if ! gh repo view "$GITHUB_REPO" &>/dev/null; then
        gh repo create "$GITHUB_REPO" \
            --public \
            --description "Foundation for a self-hosted ticket system (FastAPI + Vanilla JS)" \
            --license MIT
        info "GitHub-Repository erstellt."
    else
        warn "Repository $GITHUB_REPO existiert bereits."
    fi

    # Bereinigte Kopie erstellen
    prepare_clean_copy "$GITHUB_DIR"

    # Git-Repo initialisieren und pushen
    cd "$GITHUB_DIR"
    git init
    git config user.name "Manerba"
    git config user.email "manerba@users.noreply.github.com"
    git remote add origin "git@github.com:${GITHUB_REPO}.git"
    git add -A
    git commit -m "v${VERSION}: Initial open-source release"
    git branch -M main
    git push -u origin main --force

    info "=== GitHub Initial-Push erfolgreich ==="
    info "Repository: https://github.com/$GITHUB_REPO"
    info "Version: $VERSION"

    # Aufraeumen
    rm -rf "$GITHUB_DIR"
}

# --------------------------------------------------------------------------
# GitHub: Inkrementeller Sync
# --------------------------------------------------------------------------
github_sync() {
    read_version

    info "Synchronisiere nach GitHub ($GITHUB_REPO)..."

    # Bereinigte Kopie erstellen
    prepare_clean_copy "$GITHUB_DIR"

    # Bestehendes GitHub-Repo klonen (nur .git)
    local TEMP_GIT="/tmp/casos-github-git"
    rm -rf "$TEMP_GIT"
    git clone --bare "git@github.com:${GITHUB_REPO}.git" "$TEMP_GIT"

    # .git in die bereinigte Kopie verschieben
    mv "$TEMP_GIT" "$GITHUB_DIR/.git"

    # Bare-Repo in normales umwandeln
    cd "$GITHUB_DIR"
    git config --local --bool core.bare false
    git config user.name "Manerba"
    git config user.email "manerba@users.noreply.github.com"
    git reset HEAD -- . >/dev/null 2>&1 || true

    # Aenderungen pruefen
    if git diff --quiet HEAD && [ -z "$(git ls-files --others --exclude-standard)" ]; then
        info "Keine Aenderungen gegenueber GitHub."
        rm -rf "$GITHUB_DIR"
        return
    fi

    # Aenderungen committen und pushen
    git add -A
    git commit -m "v${VERSION}: Sync from internal repository"
    git push origin main

    info "=== GitHub Sync erfolgreich ==="
    info "Repository: https://github.com/$GITHUB_REPO"
    info "Version: $VERSION"

    # Aufraeumen
    rm -rf "$GITHUB_DIR"
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
    --github-init)
        github_init
        ;;
    --github)
        github_sync
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
        info "Install: curl -s http://$REPO_SERVER/casos/install.sh | bash"
        echo ""
        ;;
esac

# Build-Verzeichnis aufraeumen
rm -rf "$BUILD_DIR"

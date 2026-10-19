#!/bin/bash
#
# git-commit.sh - Automatisierter Commit mit Build-Nummer-Inkrement
#
# Verwendung: ./git-commit.sh [optionale Commit-Message]
#
# Ohne Message wird nur die Build-Nummer als Commit-Message verwendet.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/version.txt"

# Prüfe ob version.txt existiert
if [ ! -f "$VERSION_FILE" ]; then
    echo "Fehler: $VERSION_FILE nicht gefunden"
    exit 1
fi

# Lese aktuelle Version
CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '\n')

# Parse Version: MAJOR.MINOR.PATCH+BUILD
if [[ ! "$CURRENT_VERSION" =~ ^([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)$ ]]; then
    echo "Fehler: Ungültiges Versionsformat in $VERSION_FILE"
    echo "Erwartet: X.Y.Z+BUILD (z.B. 0.0.1+0)"
    echo "Gefunden: $CURRENT_VERSION"
    exit 1
fi

SEMVER="${BASH_REMATCH[1]}"
BUILD="${BASH_REMATCH[2]}"

# Inkrementiere Build-Nummer
NEW_BUILD=$((BUILD + 1))
NEW_VERSION="${SEMVER}+${NEW_BUILD}"

echo "Version: $CURRENT_VERSION -> $NEW_VERSION"

# Aktualisiere version.txt
echo "$NEW_VERSION" > "$VERSION_FILE"

# Git-Operationen
cd "$SCRIPT_DIR"

# Stage alle Änderungen
git add -A

# Commit-Message: nur Version, oder Version + optionale Message
if [ -n "$1" ]; then
    git commit -m "${NEW_VERSION}: $1"
else
    git commit -m "$NEW_VERSION"
fi

echo ""
echo "Commit erfolgreich: $NEW_VERSION"

# Ein neuer lokaler Klon kann noch ohne eigenes Remote betrieben werden.
if [ -z "$(git remote)" ]; then
    echo "Kein Remote konfiguriert. Commit bleibt lokal."
    exit 0
fi

# Push zum Remote
echo "Pushe zum Remote..."
git push

echo "Push erfolgreich abgeschlossen."

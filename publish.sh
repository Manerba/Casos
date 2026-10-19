#!/bin/bash
# Historical filename; this command only builds a local package.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { echo "Usage: $0 --build [output-directory]"; }
case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --build) ;;
    *) usage >&2; echo "No publication target is configured. Only --build is supported." >&2; exit 2 ;;
esac
if [ "$#" -gt 2 ]; then usage >&2; exit 2; fi
for command_name in dpkg-deb rsync; do
    command -v "$command_name" >/dev/null || { echo "Missing build tool: $command_name" >&2; exit 1; }
done
VERSION=$(tr -d '\r\n' < "$SCRIPT_DIR/version.txt")
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]]; then
    echo "Invalid version.txt" >&2; exit 1
fi
OUTPUT_DIR="${2:-$SCRIPT_DIR/dist}"
mkdir -p -- "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/casos-build.XXXXXXXX")
TEMP_DEB=""
cleanup() { rm -rf -- "$BUILD_DIR"; if [ -n "$TEMP_DEB" ]; then rm -f -- "$TEMP_DEB"; fi; }
trap cleanup EXIT
PKG_ROOT="$BUILD_DIR/package"
APP_DIR="$PKG_ROOT/opt/casos"
DOC_DIR="$PKG_ROOT/usr/share/doc/casos"
install -d -m 755 "$PKG_ROOT/DEBIAN" "$APP_DIR/dashboard" "$APP_DIR/scripts" "$DOC_DIR"
sed "s/__VERSION__/$VERSION/" "$SCRIPT_DIR/packaging/DEBIAN/control" > "$PKG_ROOT/DEBIAN/control"
chmod 644 "$PKG_ROOT/DEBIAN/control"
for hook in postinst prerm postrm; do
    install -m 755 "$SCRIPT_DIR/packaging/DEBIAN/$hook" "$PKG_ROOT/DEBIAN/$hook"
done
rsync -a --exclude='__pycache__' --exclude='*.pyc' "$SCRIPT_DIR/dashboard/" "$APP_DIR/dashboard/"
for script in ldap_sync_cron.py mail_scheduler.py; do
    install -m 644 "$SCRIPT_DIR/scripts/$script" "$APP_DIR/scripts/$script"
done
for unit in "$SCRIPT_DIR/packaging/services/"*.service "$SCRIPT_DIR/packaging/services/"*.timer; do
    install -m 644 "$unit" "$APP_DIR/scripts/"
done
install -m 644 "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/version.txt" "$APP_DIR/"
install -m 644 "$SCRIPT_DIR/LICENSE" "$DOC_DIR/copyright"
install -m 644 "$SCRIPT_DIR/packaging/README.Debian" "$SCRIPT_DIR/docs/operations.md" "$SCRIPT_DIR/packaging/DEPENDENCIES.md" "$DOC_DIR/"
sed -i 's|../packaging/DEPENDENCIES.md|DEPENDENCIES.md|g' "$DOC_DIR/operations.md"
install -m 644 "$SCRIPT_DIR/docs/casos-agent-guide.md" "$SCRIPT_DIR/docs/casos-agents-snippet.md" "$DOC_DIR/"
if [ -d "$SCRIPT_DIR/packaging/licenses" ]; then
    cp -R "$SCRIPT_DIR/packaging/licenses" "$DOC_DIR/licenses"
fi
# Shared/NTFS checkouts may mark every source file 0777. Normalize the archive.
find "$PKG_ROOT" -type d -exec chmod 755 {} +
find "$PKG_ROOT" -type f -exec chmod 644 {} +
chmod 755 "$PKG_ROOT/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/prerm" "$PKG_ROOT/DEBIAN/postrm"
# An unprivileged builder can produce the same root-owned package metadata.
TEMP_DEB=$(mktemp "$OUTPUT_DIR/.casos-${VERSION}.XXXXXXXX.deb")
dpkg-deb --root-owner-group --build "$PKG_ROOT" "$TEMP_DEB"
DEB_FILE="$OUTPUT_DIR/casos_${VERSION}_all.deb"
mv -f -- "$TEMP_DEB" "$DEB_FILE"
TEMP_DEB=""
echo "Local package: $DEB_FILE"
echo "No upload, repository change or service activation was performed."

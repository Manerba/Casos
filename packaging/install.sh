#!/bin/bash
# Install an explicitly supplied local package; no repository is configured.
set -euo pipefail
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 /absolute/path/to/casos_VERSION_all.deb" >&2; exit 2
fi
PACKAGE_FILE=$(realpath -- "$1")
if [ ! -f "$PACKAGE_FILE" ] || [ "$(dpkg-deb --field "$PACKAGE_FILE" Package)" != "casos" ]; then
    echo "Expected a local Casos DEB package." >&2; exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Run installation as root. The package installs and starts Casos services." >&2; exit 1
fi
apt-get install -- "$PACKAGE_FILE"
echo "Casos: port 8514; settings via the global gear menu. MCP: port 8516/mcp/."
echo "For a fresh database, sign in as admin / admin and change the password."

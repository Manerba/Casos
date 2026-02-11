#!/bin/bash
# ============================================================
# ONLYOFFICE Document Server - Docker Setup
# Startet den ONLYOFFICE Document Server als Docker-Container
# mit JWT-Authentifizierung und WOPI-Unterstuetzung.
# ============================================================

set -e

CONTAINER_NAME="onlyoffice-docs"
PORT=8090

# Docker pruefen
if ! command -v docker &> /dev/null; then
    echo "FEHLER: Docker ist nicht installiert."
    echo "Installation: apt install docker.io"
    exit 1
fi

# Existierenden Container pruefen
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Container '${CONTAINER_NAME}' existiert bereits."
    echo ""
    read -p "Container stoppen und neu erstellen? (j/N) " confirm
    if [[ "$confirm" =~ ^[jJyY]$ ]]; then
        echo "Stoppe und entferne Container..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
        docker rm "${CONTAINER_NAME}" 2>/dev/null || true
    else
        echo "Abgebrochen."
        exit 0
    fi
fi

# JWT Secret generieren
JWT_SECRET=$(openssl rand -hex 32)

echo "============================================"
echo "ONLYOFFICE Document Server Setup"
echo "============================================"
echo "Port:       ${PORT}"
echo "JWT Secret: ${JWT_SECRET}"
echo "============================================"
echo ""

# Container starten
echo "Starte ONLYOFFICE Document Server..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    -p "${PORT}:80" \
    -e JWT_ENABLED=true \
    -e JWT_SECRET="${JWT_SECRET}" \
    -e WOPI_ENABLED=true \
    onlyoffice/documentserver

echo ""
echo "Warte auf Healthcheck..."

# Healthcheck (max 120 Sekunden)
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sf "http://localhost:${PORT}/healthcheck" > /dev/null 2>&1; then
        echo ""
        echo "============================================"
        echo "ONLYOFFICE Document Server ist bereit!"
        echo "============================================"
        echo ""
        echo "URL:        http://$(hostname -I | awk '{print $1}'):${PORT}"
        echo "JWT Secret: ${JWT_SECRET}"
        echo ""
        echo "Trage diese Werte in der Tareas Admin-UI ein:"
        echo "  Admin -> ONLYOFFICE -> Server URL + JWT Secret"
        echo "============================================"
        exit 0
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    echo "  Warte... (${WAITED}s / ${MAX_WAIT}s)"
done

echo ""
echo "WARNUNG: Healthcheck nach ${MAX_WAIT}s nicht erfolgreich."
echo "Der Container startet moeglicherweise noch."
echo "Pruefe manuell: curl http://localhost:${PORT}/healthcheck"
echo ""
echo "JWT Secret (fuer Admin-UI): ${JWT_SECRET}"
exit 1

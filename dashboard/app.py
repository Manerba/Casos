"""
Dashboard Template - FastAPI Backend
Port 8503
"""

import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn


app = FastAPI(title="Dashboard Template")

# Verzeichnisse
static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"
project_root = Path(__file__).parent.parent

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Statische Dateien: Browser muss immer beim Server revalidieren."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ============================================================
# API-Endpunkte (muessen VOR dem Catch-All definiert werden)
# ============================================================

@app.get("/api/dashboard/info")
async def dashboard_info():
    """
    Template-Informationen und Entwickler-Hilfe.
    """
    # Version aus version.txt lesen
    version = "0.0.0"
    version_file = project_root / "version.txt"
    if version_file.exists():
        version = version_file.read_text().strip()

    return {
        "version": version,
        "title": "Dashboard Template",
        "description": "Wiederverwendbares Web-Dashboard auf Basis von FastAPI + Vanilla JS",
        "components": [
            {
                "name": "ExpandableTable",
                "description": "Sortierbare, filterbare Tabelle mit aufklappbaren Detail-Rows",
                "features": [
                    "Spalten-Konfiguration (Breite, Renderer, Sortierung)",
                    "Filter (Select, Input, Buttons, Wildcard-Suche)",
                    "Pagination (konfigurierbare Seitengroessen)",
                    "Aufklappbare Detail-Rows mit Feldern und Sektionen",
                    "Sticky Header",
                    "CSS-Grid-basiertes Layout",
                ],
            },
            {
                "name": "KPI-Cards / Widget-Dashboard",
                "description": "Dashboard-Widgets mit KPI-Karten und Tabellen",
                "features": [
                    "KPI-Karten mit Icon, Wert, Titel, Farb-Regeln",
                    "KPI-Sektionen (gruppierte Karten)",
                    "KPI-Tabellen (kompakte Darstellung)",
                    "Widget-Dashboard mit parallelem Daten-Laden",
                    "Formate: number, percent, currency, text",
                ],
            },
            {
                "name": "Theme-System",
                "description": "Light/Dark-Theme mit CSS Custom Properties",
                "features": [
                    "Persistenz via localStorage",
                    "CSS-Variablen fuer alle Farben",
                    "Theme-Toggle im Settings-Dropdown",
                    "Custom Event 'themeChanged' fuer Komponenten",
                ],
            },
            {
                "name": "Notification-System",
                "description": "Toast-Benachrichtigungen (info, success, error)",
                "features": [
                    "showNotification(message, type)",
                    "Auto-Hide nach 3 Sekunden",
                    "Typen: info, success, error",
                ],
            },
            {
                "name": "DOM-Caching",
                "description": "Tab-Inhalte werden beim Wechsel im Speicher gehalten",
                "features": [
                    "DocumentFragment-basiertes Caching",
                    "Scroll-Position wird wiederhergestellt",
                    "Filter-Zustaende bleiben erhalten",
                    "Gleicher Tab nochmal = Force-Refresh",
                ],
            },
            {
                "name": "URL-Routing",
                "description": "SPA-Routing mit Browser-History-API",
                "features": [
                    "Clientseitiges Routing mit pushState",
                    "Browser-Zurueck/Vorwaerts funktioniert",
                    "Direkte URLs moeglich (Catch-All im Backend)",
                    "Rechtsklick -> In neuem Tab oeffnen",
                ],
            },
        ],
        "how_to_add_tab": {
            "steps": [
                "1. JS-Datei erstellen: dashboard/static/js/tab_example.js",
                "2. Init-Funktion definieren: async function initExampleTab() { ... }",
                "3. In app_core.js: Tab in switchTab() registrieren",
                "4. In index.html: Tab-Link in <nav class='tabs'> + <script>-Include",
                "5. Optional: API-Endpunkt in app.py hinzufuegen",
                "6. Optional: Tabellen-Config mit ExpandableTable definieren",
            ],
            "example": "Siehe expandable_table.js und kpi_grid.js als Referenz",
        },
        "api_structure": {
            "pattern": "/api/{resource}",
            "examples": [
                "GET /api/dashboard/info - Diese Info-Seite",
                "POST /api/dashboard/restart - Server neu starten",
            ],
            "conventions": [
                "GET fuer Lesen, POST fuer Erstellen, PUT fuer Aendern, DELETE fuer Loeschen",
                "Antwort immer als JSON",
                "Fehler als { 'error': 'Beschreibung' }",
            ],
        },
    }


@app.post("/api/dashboard/restart")
async def restart_dashboard():
    """
    Startet den Dashboard-Service neu.
    """
    subprocess.Popen(
        ["systemctl", "restart", "dashboard-template.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "restarting", "message": "Dashboard wird neu gestartet..."}


# ============================================================
# HTML-Routen (Catch-All fuer SPA-Routing, NACH API-Routen)
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """Startseite."""
    return FileResponse(templates_dir / "index.html")


@app.get("/{path:path}", response_class=HTMLResponse)
async def catch_all(path: str):
    """Catch-All fuer clientseitiges Routing (SPA)."""
    return FileResponse(templates_dir / "index.html")


# ============================================================
# Start
# ============================================================

def main():
    """Dashboard starten."""
    print("=" * 50)
    print("Dashboard Template")
    print("=" * 50)
    print("URL: http://10.0.12.7:8503")
    print("Strg+C zum Beenden")
    print("=" * 50)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8503,
        log_level="info",
    )


if __name__ == "__main__":
    main()

"""
Tareas - Aufgabenplanungs-Tool
FastAPI Backend, Port 8504
"""

import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Sicherstellen, dass 'dashboard' als Package importierbar ist
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

from dashboard.database import init_db
from dashboard.api_tasks import router as tasks_router
from dashboard.api_auth import router as auth_router
from dashboard.auth import get_current_user, _extract_user_from_request


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/Shutdown Events."""
    init_db()
    yield


app = FastAPI(title="Tareas", lifespan=lifespan)

# Auth-Router OHNE globale Dependency (login muss oeffentlich sein)
app.include_router(auth_router)

# Tasks-Router MIT auth Dependency
app.include_router(tasks_router, dependencies=[Depends(get_current_user)])

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
async def dashboard_info(user=Depends(get_current_user)):
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
        "title": "Tareas",
        "description": "Aufgabenplanungs-Tool auf Basis von FastAPI + Vanilla JS",
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
async def restart_dashboard(user=Depends(get_current_user)):
    """
    Startet den Dashboard-Service neu.
    """
    subprocess.Popen(
        ["systemctl", "restart", "tareas.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "restarting", "message": "Dashboard wird neu gestartet..."}


# ============================================================
# HTML-Routen (Catch-All fuer SPA-Routing, NACH API-Routen)
# ============================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Login-Seite."""
    return FileResponse(templates_dir / "login.html")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Startseite - bei fehlendem Login -> Login-Seite."""
    user = _extract_user_from_request(request)
    if not user:
        return FileResponse(templates_dir / "login.html")
    return FileResponse(templates_dir / "index.html")


@app.get("/{path:path}", response_class=HTMLResponse)
async def catch_all(path: str, request: Request = None):
    """Catch-All fuer clientseitiges Routing (SPA)."""
    if request:
        user = _extract_user_from_request(request)
        if not user:
            return FileResponse(templates_dir / "login.html")
    return FileResponse(templates_dir / "index.html")


# ============================================================
# Start
# ============================================================

def main():
    """Dashboard starten."""
    print("=" * 50)
    print("Tareas - Aufgabenplanung")
    print("=" * 50)
    print("URL: http://10.0.12.7:8504")
    print("Strg+C zum Beenden")
    print("=" * 50)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8504,
        log_level="info",
    )


if __name__ == "__main__":
    main()

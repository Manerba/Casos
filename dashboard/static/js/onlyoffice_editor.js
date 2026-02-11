/**
 * Tareas - ONLYOFFICE Editor Integration
 * Fullscreen-Overlay mit DocsAPI.DocEditor
 */

// Editierbare Dateiformate (muss mit Backend uebereinstimmen)
const OO_EDITABLE_EXTENSIONS = new Set([
    'docx', 'doc', 'odt', 'txt', 'rtf', 'md', 'html',
    'xlsx', 'xls', 'ods', 'csv',
    'pptx', 'ppt', 'odp',
]);

let _ooEditorInstance = null;
let _ooOverlay = null;
let _ooEscHandler = null;

/**
 * Pruefen ob Dateiformat von ONLYOFFICE unterstuetzt wird.
 */
function isOnlyOfficeEditable(fileName) {
    if (!fileName) return false;
    const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
    return OO_EDITABLE_EXTENSIONS.has(ext);
}

/**
 * ONLYOFFICE Editor im Fullscreen-Overlay oeffnen.
 */
async function openOnlyOfficeEditor(taskId, filePath) {
    // Falls schon ein Editor offen ist, schliessen
    if (_ooOverlay) closeOnlyOfficeEditor();

    const fileName = filePath.includes('/') ? filePath.split('/').pop() : filePath;

    // Overlay erstellen
    const overlay = document.createElement('div');
    overlay.className = 'onlyoffice-overlay';
    overlay.innerHTML = `
        <div class="oo-header">
            <div class="oo-title">${escapeHtml(fileName)}</div>
            <div id="oo-badge-container"></div>
            <button class="oo-close-btn" id="ooCloseBtn" title="Schliessen">&times;</button>
        </div>
        <div class="oo-body" id="ooEditorBody">
            <div class="oo-loading">
                <div class="spinner"></div>
                <span>Editor wird geladen...</span>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    _ooOverlay = overlay;

    // Close-Button
    document.getElementById('ooCloseBtn').addEventListener('click', closeOnlyOfficeEditor);

    // ESC-Handler
    _ooEscHandler = (e) => {
        if (e.key === 'Escape') closeOnlyOfficeEditor();
    };
    document.addEventListener('keydown', _ooEscHandler);

    // Editor-Config vom Backend laden
    try {
        const resp = await fetch(`/api/tasks/${taskId}/files/edit?path=${encodeURIComponent(filePath)}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Fehler beim Laden der Editor-Konfiguration');
        }

        const data = await resp.json();

        // Badge anzeigen
        const badgeContainer = document.getElementById('oo-badge-container');
        if (badgeContainer) {
            if (data.can_edit) {
                badgeContainer.innerHTML = '<span class="oo-badge oo-badge-edit">Bearbeiten</span>';
            } else {
                badgeContainer.innerHTML = '<span class="oo-badge oo-badge-readonly">Nur Lesen</span>';
            }
        }

        // ONLYOFFICE JS API dynamisch laden
        await _loadOnlyOfficeApi(data.editor_url);

        // Editor-Container vorbereiten
        const body = document.getElementById('ooEditorBody');
        if (!body) return;
        body.innerHTML = '<div id="ooEditorContainer" style="width:100%;height:100%;"></div>';

        // Editor-Config mit JWT Token
        const config = data.editor_config;
        config.token = data.token;
        config.width = '100%';
        config.height = '100%';

        // Events
        config.events = {
            onReady: () => {
                // Editor ist bereit
            },
            onError: (event) => {
                const errorCode = event?.data?.errorCode || 'Unbekannt';
                showNotification(`ONLYOFFICE Fehler: ${errorCode}`, 'error');
            },
            onRequestClose: () => {
                closeOnlyOfficeEditor();
            },
        };

        // DocEditor erstellen
        _ooEditorInstance = new DocsAPI.DocEditor('ooEditorContainer', config);

    } catch (error) {
        const body = document.getElementById('ooEditorBody');
        if (body) {
            body.innerHTML = `<div class="oo-loading" style="color:var(--color-bearish, #e74c3c)">${escapeHtml(error.message)}</div>`;
        }
        showNotification(error.message, 'error');
    }
}

/**
 * ONLYOFFICE Editor schliessen und Overlay entfernen.
 */
function closeOnlyOfficeEditor() {
    // Editor destroyen
    if (_ooEditorInstance) {
        try {
            _ooEditorInstance.destroyEditor();
        } catch (e) {
            // Ignorieren
        }
        _ooEditorInstance = null;
    }

    // Overlay entfernen
    if (_ooOverlay) {
        _ooOverlay.remove();
        _ooOverlay = null;
    }

    // ESC-Handler entfernen
    if (_ooEscHandler) {
        document.removeEventListener('keydown', _ooEscHandler);
        _ooEscHandler = null;
    }
}

/**
 * ONLYOFFICE JS API dynamisch laden (einmalig).
 */
function _loadOnlyOfficeApi(editorUrl) {
    return new Promise((resolve, reject) => {
        // Bereits geladen?
        if (typeof DocsAPI !== 'undefined') {
            resolve();
            return;
        }

        const script = document.createElement('script');
        script.src = `${editorUrl}/web-apps/apps/api/documents/api.js`;
        script.onload = resolve;
        script.onerror = () => reject(new Error('ONLYOFFICE API konnte nicht geladen werden'));
        document.head.appendChild(script);
    });
}

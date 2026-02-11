/**
 * Tareas Admin - ONLYOFFICE-Tab
 * ONLYOFFICE Document Server Konfiguration
 */

let ooConfig = null;

// ========================================
// Tab Initialisierung
// ========================================

async function initOnlyOfficeTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    const filterBar = document.getElementById('filterBar');
    if (filterBar) filterBar.style.display = 'none';

    await loadOoConfig();
    renderOnlyOfficeTab();
}

async function loadOoConfig() {
    try {
        const resp = await fetch('/api/admin/onlyoffice/config');
        if (!resp.ok) throw new Error('Fehler beim Laden');
        const data = await resp.json();
        ooConfig = data.config;
    } catch (e) {
        ooConfig = null;
    }
}

// ========================================
// Rendering
// ========================================

function renderOnlyOfficeTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    const hasConfig = !!ooConfig;

    let html = '<div class="ldap-container">';

    // ONLYOFFICE-Server Konfiguration
    html += renderOoConfigSection(hasConfig);

    html += '</div>';
    container.innerHTML = html;
}

function renderOoConfigSection(hasConfig) {
    const c = ooConfig || {};
    let html = `
        <div class="ldap-section">
            <h3>ONLYOFFICE Document Server</h3>
            <div class="ldap-form">
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>Server-URL</label>
                        <input type="text" id="ooServerUrl" value="${escapeAttr(c.server_url || '')}"
                               placeholder="http://10.0.12.7:8090">
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>JWT Secret</label>
                        <input type="password" id="ooJwtSecret"
                               value="${hasConfig ? escapeAttr(c.jwt_secret || '') : ''}"
                               placeholder="JWT Secret vom Docker-Setup" autocomplete="new-password">
                    </div>
                </div>
                <div class="ldap-form-actions">
                    <button class="action-btn primary" onclick="saveOoConfig()">Speichern</button>
                    <button class="action-btn" onclick="testOoConnection()">Verbindung testen</button>
                    ${hasConfig ? '<button class="action-btn danger" onclick="deleteOoConfig()">Loeschen</button>' : ''}
                </div>
            </div>`;

    // Status-Anzeige
    if (hasConfig) {
        html += `
            <div class="ldap-status-info">
                <strong>Aktive Konfiguration:</strong>
                ${escapeHtml(c.server_url)} | JWT: ${escapeHtml(c.jwt_secret)}
            </div>`;
    }

    // Setup-Hinweis
    html += `
        <div class="ldap-status-info" style="margin-top: 12px; opacity: 0.8;">
            <strong>Setup:</strong>
            Docker-Container starten mit <code>scripts/onlyoffice-setup.sh</code>.
            Das Script gibt die URL und das JWT Secret aus.
        </div>`;

    html += '</div>';
    return html;
}

// ========================================
// Config CRUD
// ========================================

async function saveOoConfig() {
    const server_url = document.getElementById('ooServerUrl')?.value?.trim();
    const jwt_secret = document.getElementById('ooJwtSecret')?.value?.trim();

    if (!server_url || !jwt_secret) {
        showNotification('Bitte alle Felder ausfuellen', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/admin/onlyoffice/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_url, jwt_secret }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Fehler beim Speichern');
        }

        showNotification('ONLYOFFICE-Konfiguration gespeichert', 'success');
        await loadOoConfig();
        renderOnlyOfficeTab();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function testOoConnection() {
    try {
        const resp = await fetch('/api/admin/onlyoffice/test');
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Verbindungstest fehlgeschlagen');
        }

        showNotification('ONLYOFFICE Document Server ist erreichbar', 'success');
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function deleteOoConfig() {
    if (!await msgbox('cancel/yes', 'warning', 'ONLYOFFICE-Konfiguration wirklich loeschen?')) return;

    try {
        const resp = await fetch('/api/admin/onlyoffice/config', { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler beim Loeschen');

        showNotification('ONLYOFFICE-Konfiguration geloescht', 'success');
        ooConfig = null;
        renderOnlyOfficeTab();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

/**
 * Tareas Admin - Nextcloud-Tab
 * Nextcloud-Konfiguration (WebDAV-Verbindung)
 */

let ncConfig = null;

// ========================================
// Tab Initialisierung
// ========================================

async function initNextcloudTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    const filterBar = document.getElementById('filterBar');
    if (filterBar) filterBar.style.display = 'none';

    await loadNcConfig();
    renderNextcloudTab();
}

async function loadNcConfig() {
    try {
        const resp = await fetch('/api/admin/nextcloud/config');
        if (!resp.ok) throw new Error('Fehler beim Laden');
        const data = await resp.json();
        ncConfig = data.config;
    } catch (e) {
        ncConfig = null;
    }
}

// ========================================
// Rendering
// ========================================

function renderNextcloudTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    const hasConfig = !!ncConfig;

    let html = '<div class="ldap-container">';

    // Nextcloud-Server Konfiguration
    html += renderNcConfigSection(hasConfig);

    html += '</div>';
    container.innerHTML = html;
}

function renderNcConfigSection(hasConfig) {
    const c = ncConfig || {};
    let html = `
        <div class="ldap-section">
            <h3>Nextcloud-Verbindung (WebDAV)</h3>
            <div class="ldap-form">
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>Nextcloud-URL</label>
                        <input type="text" id="ncServerUrl" value="${escapeAttr(c.server_url || '')}"
                               placeholder="https://cloud.firma.de">
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>Benutzername</label>
                        <input type="text" id="ncUsername" value="${escapeAttr(c.username || '')}"
                               placeholder="service-account">
                    </div>
                    <div class="ldap-form-field">
                        <label>Passwort / App-Passwort</label>
                        <input type="password" id="ncPassword"
                               value="${hasConfig ? '********' : ''}"
                               placeholder="Passwort..." autocomplete="new-password">
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>Wurzelverzeichnis</label>
                        <input type="text" id="ncBasePath" value="${escapeAttr(c.base_path || '')}"
                               placeholder="/Projekte">
                    </div>
                </div>
                <div class="ldap-form-actions">
                    <button class="action-btn primary" onclick="saveNcConfig()">Verbindung testen &amp; Speichern</button>
                    ${hasConfig ? '<button class="action-btn danger" onclick="deleteNcConfig()">Loeschen</button>' : ''}
                </div>
            </div>`;

    // Status-Anzeige
    if (hasConfig) {
        html += `
            <div class="ldap-status-info">
                <strong>Aktive Konfiguration:</strong>
                ${escapeHtml(c.server_url)} | Benutzer: ${escapeHtml(c.username)} | Pfad: ${escapeHtml(c.base_path)}
            </div>`;
    }

    html += '</div>';
    return html;
}

// ========================================
// Config CRUD
// ========================================

async function saveNcConfig() {
    const server_url = document.getElementById('ncServerUrl')?.value?.trim();
    const username = document.getElementById('ncUsername')?.value?.trim();
    const password = document.getElementById('ncPassword')?.value;
    const base_path = document.getElementById('ncBasePath')?.value?.trim();

    if (!server_url || !username || !password || !base_path) {
        showNotification('Bitte alle Felder ausfuellen', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/admin/nextcloud/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_url, username, password, base_path }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Fehler beim Speichern');
        }

        showNotification('Nextcloud-Konfiguration gespeichert (Verbindung OK)', 'success');
        await loadNcConfig();
        renderNextcloudTab();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function deleteNcConfig() {
    if (!await msgbox('cancel/yes', 'warning', 'Nextcloud-Konfiguration wirklich loeschen? Alle Verzeichniszuordnungen werden entfernt.')) return;

    try {
        const resp = await fetch('/api/admin/nextcloud/config', { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler beim Loeschen');

        showNotification('Nextcloud-Konfiguration geloescht', 'success');
        ncConfig = null;
        renderNextcloudTab();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

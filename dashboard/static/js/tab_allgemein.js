/**
 * Tareas Admin - Allgemein-Tab
 * Server-Adresse und allgemeine App-Konfiguration
 */

let appConfig = null;

async function initAllgemeinTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    const filterBar = document.getElementById('filterBar');
    if (filterBar) filterBar.style.display = 'none';

    await loadAppConfig();
    renderAllgemeinTab();
}

async function loadAppConfig() {
    try {
        const resp = await fetch('/api/admin/app/config');
        if (!resp.ok) throw new Error('Fehler beim Laden');
        const data = await resp.json();
        appConfig = data.config;
    } catch (e) {
        appConfig = null;
    }
}

function renderAllgemeinTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    const c = appConfig || {};

    container.innerHTML = `
        <div class="mail-container">
            <div class="mail-section">
                <h3>Server-Adresse</h3>
                <div class="mail-form">
                    <div class="mail-form-row">
                        <div class="mail-form-field">
                            <label>Server-Adresse</label>
                            <input type="text" id="appServerAddress"
                                   value="${escapeAttr(c.server_address || '')}"
                                   placeholder="z.B. tareas.domain.tld oder 10.0.12.7:8504">
                            <small style="color: var(--text-muted); margin-top: 4px; display: block;">
                                Protokoll (http/https) wird automatisch aus den TLS-Einstellungen abgeleitet.
                                Diese Adresse wird in E-Mails als Link zur App verwendet.
                            </small>
                        </div>
                    </div>
                    <div class="mail-form-actions">
                        <button class="action-btn primary" onclick="saveAppConfig()">Speichern</button>
                    </div>
                </div>
            </div>
        </div>`;
}

async function saveAppConfig() {
    const server_address = document.getElementById('appServerAddress')?.value?.trim();

    if (!server_address) {
        showNotification('Bitte Server-Adresse eingeben', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/admin/app/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_address }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Fehler beim Speichern');
        }

        showNotification('App-Konfiguration gespeichert', 'success');
        await loadAppConfig();
        renderAllgemeinTab();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

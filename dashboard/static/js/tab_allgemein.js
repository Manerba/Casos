/**
 * Casos Einstellungen - Allgemein-Tab
 * Server-Adresse und allgemeine App-Konfiguration
 */

let appConfig = null;

async function initAllgemeinTab() {
    await settingsInitSection('allgemein', {
        showFilterBar: false,
        loadFn: loadAppConfig,
        renderFn: renderAllgemeinTab,
    });
}

async function loadAppConfig() {
    appConfig = await settingsLoadConfig('/api/admin/app/config');
}

function renderAllgemeinTab() {
    const container = settingsContainer('allgemein');
    if (!container) return;

    const c = appConfig || {};

    settingsRender('allgemein', `
        <div class="mail-container">
            <div class="mail-section">
                <h3>${t('allgemein.title')}</h3>
                <div class="mail-form">
                    <div class="mail-form-row">
                        <div class="mail-form-field">
                            <label>${t('allgemein.serverAddress')}</label>
                            <input type="text" id="appServerAddress"
                                   value="${escapeAttr(c.server_address || '')}"
                                   placeholder="${t('allgemein.placeholder')}">
                            <small style="color: var(--text-muted); margin-top: 4px; display: block;">
                                ${t('allgemein.hint')}
                            </small>
                        </div>
                    </div>
                    <div class="mail-form-actions">
                        <button class="action-btn primary" onclick="saveAppConfig()">${t('common.save')}</button>
                    </div>
                </div>
            </div>
        </div>`);
}

async function saveAppConfig() {
    return settingsAction(async () => {
    const server_address = settingsField('allgemein', 'appServerAddress')?.value?.trim();

    if (!server_address) {
        settingsNotify(t('allgemein.addressRequired'), 'error');
        return;
    }

    await settingsSaveConfig({
        section: 'allgemein', fields: ['appServerAddress'],
        endpoint: '/api/admin/app/config',
        data: { server_address },
        successMessage: t('allgemein.saved'),
        onSuccess: async () => {
            await loadAppConfig();
            renderAllgemeinTab();
        },
    });
    });
}

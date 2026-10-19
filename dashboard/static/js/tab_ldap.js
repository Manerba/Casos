/**
 * Casos Einstellungen - LDAP-Tab
 * LDAP-Konfiguration und AD-Gruppen-Verwaltung
 */

let ldapConfig = null;

// ========================================
// Tab Initialisierung
// ========================================

async function initLdapTab() {
    await settingsInitSection('ldap', {
        showFilterBar: false,
        loadFn: loadLdapConfig,
        renderFn: renderLdapTab,
    });
}

async function loadLdapConfig() {
    ldapConfig = await settingsLoadConfig('/api/admin/ldap/config');
}

// ========================================
// Rendering
// ========================================

function renderLdapTab() {
    const container = settingsContainer('ldap');
    if (!container) return;

    const hasConfig = !!ldapConfig;
    const hasGroup = hasConfig && !!ldapConfig.group_dn;

    let html = '<div class="ldap-container">';

    // Sektion 1: LDAP-Server Konfiguration
    html += renderConfigSection(hasConfig);

    // Sektion 2: AD-Gruppe (nur wenn Config vorhanden)
    if (hasConfig) {
        html += renderGroupSection(hasGroup);
    }

    html += '</div>';
    settingsRender('ldap', html);

    // SSL-Checkbox Event
    const sslCheckbox = settingsField('ldap', 'ldapUseSSL');
    if (sslCheckbox) {
        sslCheckbox.addEventListener('change', function() {
            const portInput = settingsField('ldap', 'ldapPort');
            if (portInput) {
                portInput.value = this.checked ? 636 : 389;
            }
        });
    }
}

function renderConfigSection(hasConfig) {
    const c = ldapConfig || {};
    let html = `
        <div class="ldap-section">
            <h3>${t('ldap.title')}</h3>
            <div class="ldap-form">
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>${t('ldap.server')}</label>
                        <input type="text" id="ldapServer" value="${escapeAttr(c.server || '')}"
                               placeholder="ldap.example.local oder dc.firma.local">
                    </div>
                    <div class="ldap-form-field" style="max-width:120px">
                        <label>${t('ldap.port')}</label>
                        <input type="number" id="ldapPort" value="${c.port || 389}">
                    </div>
                    <div class="ldap-form-field" style="max-width:80px">
                        <label>${t('ldap.ssl')}</label>
                        <label class="ldap-checkbox">
                            <input type="checkbox" id="ldapUseSSL" ${c.use_ssl ? 'checked' : ''}>
                            SSL
                        </label>
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>${t('ldap.bindDn')}</label>
                        <input type="text" id="ldapBindDN" value="${escapeAttr(c.bind_dn || '')}"
                               placeholder="CN=ldapreader,OU=Service,DC=firma,DC=local">
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>${t('ldap.bindPassword')}</label>
                        <input type="password" id="ldapBindPassword"
                               value="${escapeAttr(c.bind_password || '')}"
                               placeholder="${t('auth.password')}..." autocomplete="new-password">
                    </div>
                </div>
                <div class="ldap-form-row">
                    <div class="ldap-form-field">
                        <label>${t('ldap.searchBase')}</label>
                        <input type="text" id="ldapSearchBase" value="${escapeAttr(c.search_base || '')}"
                               placeholder="OU=Benutzer,DC=firma,DC=local">
                    </div>
                    <div class="ldap-form-field" style="max-width:180px">
                        <label>${t('ldap.syncInterval')}</label>
                        <input type="number" id="ldapSyncInterval" value="${c.sync_interval_minutes || 60}" min="5">
                    </div>
                </div>
                <div class="ldap-form-actions">
                    <button class="action-btn primary" onclick="saveLdapConfig()">${t('ldap.testAndSave')}</button>
                    ${hasConfig ? `<button class="action-btn danger" onclick="deleteLdapConfig()">${t('common.delete')}</button>` : ''}
                </div>
            </div>`;

    // Status-Anzeige
    if (hasConfig) {
        const ssl = c.use_ssl ? t('common.yes') : t('common.no');
        const lastSync = c.last_sync_at || t('ldap.never');
        html += `
            <div class="ldap-status-info">
                <strong>${t('ldap.activeConfig')}</strong>
                ${escapeHtml(c.server)}:${c.port} | SSL: ${ssl} | ${t('ldap.searchBase')}: ${escapeHtml(c.search_base)} | ${t('ldap.lastSync')} ${lastSync}
            </div>`;
    }

    html += '</div>';
    return html;
}

function renderGroupSection(hasGroup) {
    let html = '<div class="ldap-section">';
    html += `<h3>${t('ldap.group')}</h3>`;

    if (hasGroup) {
        // Gruppe ist gewaehlt
        html += `
            <div class="ldap-group-selected">
                <div class="ldap-group-info">
                    <span class="badge badge-ldap">${t('ldap.selected')}</span>
                    <strong>${escapeHtml(ldapConfig.group_name)}</strong>
                    <span class="ldap-group-dn">${escapeHtml(ldapConfig.group_dn)}</span>
                </div>
                <button class="action-btn danger" onclick="deselectGroup()">${t('ldap.deselect')}</button>
            </div>
            <div class="ldap-sync-bar">
                <button class="action-btn primary" onclick="manualSync()">${t('ldap.syncNow')}</button>
                <span class="ldap-last-sync">${t('ldap.lastSync')} ${ldapConfig.last_sync_at || t('ldap.never')}</span>
            </div>
            <div class="ldap-hint">${t('ldap.hint')}</div>`;
    } else {
        // Gruppen-Liste laden
        html += `
            <div id="ldapGroupsList">
                <button class="action-btn" onclick="loadGroups()">${t('ldap.loadGroups')}</button>
            </div>`;
    }

    html += '</div>';
    return html;
}

// ========================================
// LDAP Config CRUD
// ========================================

async function saveLdapConfig() {
    return settingsAction(async () => {
    const server = settingsField('ldap', 'ldapServer')?.value?.trim();
    const port = parseInt(settingsField('ldap', 'ldapPort')?.value) || 389;
    const use_ssl = settingsField('ldap', 'ldapUseSSL')?.checked ? 1 : 0;
    const bind_dn = settingsField('ldap', 'ldapBindDN')?.value?.trim();
    const bind_password = settingsField('ldap', 'ldapBindPassword')?.value;
    const search_base = settingsField('ldap', 'ldapSearchBase')?.value?.trim();
    const sync_interval_minutes = parseInt(settingsField('ldap', 'ldapSyncInterval')?.value) || 60;

    if (!server || !bind_dn || !bind_password || !search_base) {
        settingsNotify(t('common.fillRequired'), 'error');
        return;
    }

    await settingsSaveConfig({
        section: 'ldap', fields: ['ldapServer', 'ldapPort', 'ldapUseSSL', 'ldapBindDN', 'ldapBindPassword', 'ldapSearchBase', 'ldapSyncInterval'],
        endpoint: '/api/admin/ldap/config',
        data: { server, port, use_ssl, bind_dn, bind_password, search_base, sync_interval_minutes },
        successMessage: t('ldap.saved'),
        onSuccess: async () => {
            await loadLdapConfig();
            renderLdapTab();
        },
    });
    });
}

async function deleteLdapConfig() {
    return settingsAction(async () => {
    await settingsDeleteConfig({
        section: 'ldap', fields: ['ldapServer', 'ldapPort', 'ldapUseSSL', 'ldapBindDN', 'ldapBindPassword', 'ldapSearchBase', 'ldapSyncInterval'],
        endpoint: '/api/admin/ldap/config',
        confirmMessage: t('ldap.deleteConfirm'),
        successMessage: t('ldap.deleted'),
        onSuccess: () => {
            ldapConfig = null;
            renderLdapTab();
        },
    });
    });
}

// ========================================
// Gruppen
// ========================================

async function loadGroups() {
    const container = settingsField('ldap', 'ldapGroupsList');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    try {
        const resp = await settingsFetch('/api/admin/ldap/groups');
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || t('common.loadError'));
        }

        const data = await resp.json();
        const groups = data.groups || [];

        if (groups.length === 0) {
            container.innerHTML = `<p class="ldap-hint">${t('ldap.noGroups')}</p>`;
            return;
        }

        let html = `
            <table class="ldap-groups-table">
                <thead>
                    <tr><th>${t('ldap.groupName')}</th><th>${t('ldap.groupDn')}</th><th style="width:60px"></th></tr>
                </thead>
                <tbody>`;

        for (const [index, group] of groups.entries()) {
            html += `
                <tr>
                    <td>${escapeHtml(group.name)}</td>
                    <td class="ldap-group-dn">${escapeHtml(group.dn)}</td>
                    <td><button class="action-btn primary" style="padding:2px 10px"
                            data-ldap-group="${index}">+</button></td>
                </tr>`;
        }

        html += '</tbody></table>';
        container.innerHTML = html;
        container.querySelectorAll('[data-ldap-group]').forEach(button => {
            const group = groups[Number(button.dataset.ldapGroup)];
            button.onclick = () => selectGroup(group.dn, group.name);
        });
    } catch (error) {
        container.innerHTML = '';
        settingsNotify(error.message, 'error');
    }
}

async function selectGroup(dn, name) {
    return settingsAction(async () => {
    try {
        const resp = await settingsFetch('/api/admin/ldap/group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_dn: dn, group_name: name }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || t('common.error'));
        }

        const data = await resp.json();
        const sync = data.sync || {};
        settingsNotify(
            t('ldap.groupSelected', { name, created: sync.created || 0, updated: sync.updated || 0 }),
            'success'
        );

        await loadLdapConfig();
        renderLdapTab();
    } catch (error) {
        settingsNotify(error.message, 'error');
    }
    });
}

async function deselectGroup() {
    return settingsAction(async () => {
    if (!await settingsConfirm(t('ldap.deselectConfirm'))) return;

    try {
        const resp = await settingsFetch('/api/admin/ldap/group', { method: 'DELETE' });
        if (!resp.ok) throw new Error(t('common.error'));

        settingsNotify(t('ldap.deselected'), 'success');
        await loadLdapConfig();
        renderLdapTab();
    } catch (error) {
        settingsNotify(error.message, 'error');
    }
    });
}

// ========================================
// Sync
// ========================================

async function manualSync() {
    return settingsAction(async () => {
    try {
        const resp = await settingsFetch('/api/admin/ldap/sync', { method: 'POST' });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || t('ldap.syncFailed'));
        }

        const data = await resp.json();
        const sync = data.sync || {};
        settingsNotify(
            t('ldap.syncComplete', { created: sync.created || 0, updated: sync.updated || 0, deactivated: sync.deactivated || 0 }),
            'success'
        );

        await loadLdapConfig();
        renderLdapTab();
    } catch (error) {
        settingsNotify(error.message, 'error');
    }
    });
}

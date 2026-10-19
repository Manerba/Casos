/** Scoped settings panels. Their DOM and drafts never replace the issue view. */
let settingsState = null;
let settingsOpening = false;
const SETTINGS_SECTIONS = ['personal', 'allgemein', 'benutzer', 'ldap', 'mail', 'tls', 'mcp'];
const SETTINGS_INIT = {allgemein: 'initAllgemeinTab', benutzer: 'initBenutzerTab', ldap: 'initLdapTab', mail: 'initMailTab', tls: 'initTlsTab', mcp: 'initMcpTab'};

function settingsContainer(section) { return settingsState?.panels.get(section)?.element || null; }
function settingsField(section, id) {
    const child = settingsState?.dialogs.at(-1);
    return child?.querySelector('#' + CSS.escape(id)) || settingsContainer(section)?.querySelector('#' + CSS.escape(id));
}
function settingsValues(element) {
    const values = new Map();
    element?.querySelectorAll('input[id],select[id],textarea[id]').forEach(field => {
        if (!field.readOnly && !field.dataset.settingsTransient) values.set(field.id, field.type === 'checkbox' ? field.checked : field.value);
    });
    return values;
}
function settingsDirty(section) {
    const panel = settingsState?.panels.get(section);
    const dirty = new Map();
    if (panel) settingsValues(panel.element).forEach((value, id) => {
        if (panel.baseline.has(id) && panel.baseline.get(id) !== value) dirty.set(id, value);
    });
    return dirty;
}
function settingsMarkSaved(section, ids = null) {
    const panel = settingsState?.panels.get(section);
    if (panel) settingsValues(panel.element).forEach((value, id) => {
        if (!ids || ids.includes(id)) panel.baseline.set(id, value);
    });
}
function settingsRender(section, html) {
    const panel = settingsState?.panels.get(section);
    if (!panel) return;
    const drafts = settingsDirty(section);
    panel.element.innerHTML = html;
    panel.baseline = settingsValues(panel.element);
    drafts.forEach((value, id) => {
        const input = panel.element.querySelector('#' + CSS.escape(id));
        if (input) { if (input.type === 'checkbox') input.checked = value; else input.value = value; }
    });
}

async function settingsAction(action) {
    const state = settingsState;
    if (!state || state.busy) return;
    state.busy++;
    const disabled = [...state.root.querySelectorAll('button,input,select,textarea')].map(el => [el, el.disabled]);
    disabled.forEach(([el]) => { el.disabled = true; });
    try { return await action(); }
    finally { state.busy--; disabled.forEach(([el, value]) => { el.disabled = value; }); }
}
async function settingsFetch(url, options = {}) {
    const state = settingsState;
    const mutating = options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase());
    if (mutating && state?.requestBusy) throw new Error(t('settingsOverlay.saving'));
    if (mutating && state) state.requestBusy = true;
    try {
        const response = await fetch(url, options);
        // Read the complete body before releasing the network mutation guard.
        if (mutating) await response.clone().arrayBuffer();
        return response;
    } finally { if (mutating && state) state.requestBusy = false; }
}
async function settingsRequest(url, options = {}) {
    const response = await settingsFetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        if (data.code === 'restart_failed') throw new Error(t('settingsOverlay.restartFailed'));
        const detail = data.detail;
        throw new Error(typeof detail === 'string' ? detail : t('common.loadError') + ' (' + response.status + ')');
    }
    return data;
}
async function settingsLoadConfig(url) {
    const data = await settingsRequest(url);
    return Object.hasOwn(data, 'config') ? data.config : data;
}
async function settingsInitSection(section, config) {
    const panel = settingsState?.panels.get(section);
    if (!panel) return;
    panel.element.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';
    try {
        if (config.loadFn) await config.loadFn();
        if (settingsState?.panels.get(section) !== panel) return;
        config.renderFn();
        panel.loaded = true;
        panel.baseline = settingsValues(panel.element);
    } catch (error) {
        if (!panel.element.isConnected) return;
        panel.element.innerHTML = `<p role="alert">${escapeHtml(error.message)}</p><button class="action-btn" data-retry>${t('settingsOverlay.retry')}</button>`;
        panel.element.querySelector('[data-retry]').onclick = () => settingsInitSection(section, config);
    }
}
async function settingsSaveConfig(config) {
    try {
        await settingsRequest(config.endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(config.data)});
        settingsMarkSaved(config.section, config.fields);
        settingsNotify(config.successMessage, 'success');
        if (config.onSuccess) await config.onSuccess();
        return true;
    } catch (error) { settingsNotify(error.message, 'error'); return false; }
}
async function settingsDeleteConfig(config) {
    if (!await settingsConfirm(config.confirmMessage)) return false;
    try {
        await settingsRequest(config.endpoint, {method: 'DELETE'});
        settingsMarkSaved(config.section, config.fields);
        if (config.onSuccess) await config.onSuccess();
        settingsNotify(config.successMessage, 'success');
        return true;
    } catch (error) { settingsNotify(error.message, 'error'); return false; }
}

function settingsCreateModal(config) {
    if (!settingsState) return null;
    const overlay = document.createElement('div');
    overlay.className = 'settings-subdialog';
    overlay._returnFocus = document.activeElement;
    overlay._config = config;
    overlay.innerHTML = `<div class="modal-content ${config.cssClass || ''}" role="dialog" aria-modal="true" aria-label="${escapeAttr(config.title)}" tabindex="-1"><div class="modal-header">${config.title}</div><div class="modal-body">${config.body}</div><div class="modal-footer">${config.footer || `<button class="action-btn" data-settings-cancel>${t('common.cancel')}</button>`}</div></div>`;
    overlay.querySelector('[data-settings-cancel]')?.addEventListener('click', () => settingsCloseModal());
    settingsState.root.appendChild(overlay);
    settingsState.dialogs.push(overlay);
    config.onOpen?.(overlay);
    overlay._baseline = settingsValues(overlay);
    (overlay.querySelector('input,button,textarea,select') || overlay.firstElementChild).focus();
    return overlay;
}
async function settingsCloseModal(force = false) {
    const state = settingsState;
    const overlay = state?.dialogs.at(-1);
    if (!overlay || (state.busy && !force && !overlay._config.confirmation)) return false;
    const dirty = [...settingsValues(overlay)].some(([id, value]) => overlay._baseline.get(id) !== value);
    if (!force && dirty && !await settingsConfirm(t('settingsOverlay.discard'))) return false;
    if (state.dialogs.at(-1) !== overlay) return false;
    state.dialogs.pop();
    overlay.remove();
    overlay._config.onClose?.();
    overlay._returnFocus?.isConnected && overlay._returnFocus.focus();
    return true;
}
function settingsConfirm(message) {
    return new Promise(resolve => {
        const overlay = settingsCreateModal({confirmation: true, title: t('settingsOverlay.title'), body: `<p>${escapeHtml(message)}</p>`, footer: `<button class="action-btn" data-no>${t('common.cancel')}</button><button class="action-btn primary" data-yes>${t('common.yes')}</button>`, onClose: () => resolve(false)});
        if (!overlay) return resolve(false);
        overlay.querySelector('[data-no]').onclick = () => settingsCloseModal(true);
        overlay.querySelector('[data-yes]').onclick = () => { resolve(true); settingsCloseModal(true); };
    });
}
async function settingsClose() {
    const state = settingsState;
    if (!state) return;
    if (state.dialogs.length) return settingsCloseModal();
    if (state.busy) return;
    if (SETTINGS_SECTIONS.some(section => settingsDirty(section).size) && !await settingsConfirm(t('settingsOverlay.discard'))) return;
    if (settingsState !== state) return;
    document.removeEventListener('keydown', state.onKey, true);
    state.root.close();
    state.root.remove();
    state.inert.forEach(([element, inert]) => { element.inert = inert; });
    document.body.style.overflow = state.overflow;
    settingsState = null;
    if (state.returnFocus?.isConnected) state.returnFocus.focus();
    const url = new URL(location.href);
    if (url.searchParams.has('settings')) { url.searchParams.delete('settings'); history.replaceState(history.state, '', url); }
    window.dispatchEvent(new Event('settings-closed'));
}
function settingsKey(event) {
    const state = settingsState;
    if (!state) return;
    if (event.key === 'Escape') {
        event.preventDefault(); event.stopImmediatePropagation();
        const top = state.dialogs.at(-1);
        if (top?._config.closeOnEscape === false) return;
        settingsClose();
    } else if (event.key === 'Tab') {
        const target = state.dialogs.at(-1) || state.root;
        const focusable = [...target.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
        if (!focusable.length) { event.preventDefault(); return; }
        const first = focusable[0], last = focusable.at(-1);
        if (event.shiftKey && (document.activeElement === first || !target.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !target.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
        event.stopImmediatePropagation();
    }
}
async function openSettingsOverlay(section = 'personal') {
    if (settingsState) return settingsSelectSection(section);
    if (settingsOpening) return;
    settingsOpening = true;
    try {
        const data = await settingsRequest('/api/auth/me');
        const root = document.createElement('dialog');
        root.className = 'settings-overlay';
        root.setAttribute('aria-labelledby', 'settings-title');
        root.addEventListener('cancel', event => {event.preventDefault(); settingsClose();});
        root.innerHTML = `<div class="settings-dialog"><header><h2 id="settings-title">${t('settingsOverlay.title')}</h2><button class="action-btn" data-settings-close aria-label="${escapeAttr(t('common.close'))}">×</button></header><div class="settings-layout"><nav aria-label="${escapeAttr(t('settingsOverlay.title'))}"></nav><div class="settings-panels"></div></div><footer><button class="action-btn" data-settings-close>${t('common.close')}</button></footer></div>`;
        const allowed = data.user.is_admin ? SETTINGS_SECTIONS : ['personal'];
        settingsState = {root, panels: new Map(), dialogs: [], busy: 0, user: data.user, returnFocus: document.activeElement, overflow: document.body.style.overflow, inert: [], onKey: settingsKey};
        for (const name of allowed) {
            const button = document.createElement('button');
            button.type = 'button'; button.textContent = t(name === 'personal' ? 'settingsOverlay.personal' : 'nav.' + name); button.dataset.section = name;
            button.onclick = () => settingsSelectSection(name);
            root.querySelector('nav').appendChild(button);
            const panel = document.createElement('section'); panel.className = 'settings-panel'; panel.dataset.section = name; panel.hidden = true;
            root.querySelector('.settings-panels').appendChild(panel);
            settingsState.panels.set(name, {element: panel, baseline: new Map(), loaded: false, loading: false});
        }
        [...document.body.children].forEach(element => { if (element.tagName !== 'SCRIPT') { settingsState.inert.push([element, element.inert]); element.inert = true; } });
        document.body.appendChild(root); root.showModal(); document.body.style.overflow = 'hidden';
        root.querySelectorAll('[data-settings-close]').forEach(button => { button.onclick = settingsClose; });
        document.addEventListener('keydown', settingsKey, true);
        await settingsSelectSection(allowed.includes(section) ? section : 'personal');
        root.querySelector('nav button[aria-current="true"]')?.focus();
    } catch (error) { settingsNotify(error.message, 'error'); }
    finally { settingsOpening = false; }
}
async function settingsSelectSection(section) {
    const state = settingsState;
    if (!state || state.busy || state.dialogs.length) return;
    const panel = state.panels.get(section);
    if (!panel) return;
    state.panels.forEach((value, key) => { value.element.hidden = key !== section; });
    state.root.querySelectorAll('nav button').forEach(button => button.setAttribute('aria-current', String(button.dataset.section === section)));
    state.root.querySelector('nav button[aria-current="true"]')?.scrollIntoView({block:'nearest',inline:'nearest'});
    if (!panel.loaded && !panel.loading) {
        panel.loading = true;
        try { if (section === 'personal') await settingsInitPersonal(); else await window[SETTINGS_INIT[section]](); }
        finally { panel.loading = false; }
    }
}

async function settingsInitPersonal() {
    await settingsInitSection('personal', {loadFn: async () => {}, renderFn: () => {
        settingsRender('personal', `<section class="mail-section"><h3>${t('settings.colorScheme')}</h3><select id="settingsScheme">${COLOR_SCHEMES.map(s => `<option value="${s.code}" ${s.code === getColorScheme() ? 'selected' : ''}>${escapeHtml(t(s.i18nKey))}</option>`).join('')}</select></section><section class="mail-section"><h3>${t('password.change')}</h3><label>${t('password.old')}<input type="password" id="settingsOldPassword" autocomplete="current-password"></label><label>${t('password.new')}<input type="password" id="settingsNewPassword" autocomplete="new-password"></label><label>${t('password.confirm')}<input type="password" id="settingsConfirmPassword" autocomplete="new-password"></label><button class="action-btn primary" id="settingsPasswordSave">${t('common.save')}</button></section><section class="mail-section" id="settingsPreferences"><h3>${t('settings.mailNotifications')}</h3><button class="action-btn" id="settingsLoadPreferences">${t('settingsOverlay.loadPreferences')}</button></section>`);
        settingsField('personal', 'settingsScheme').onchange = event => { setColorScheme(event.target.value); settingsMarkSaved('personal', ['settingsScheme']); };
        settingsField('personal', 'settingsPasswordSave').onclick = settingsSavePassword;
        settingsField('personal', 'settingsLoadPreferences').onclick = settingsLoadPreferences;
    }});
}
async function settingsSavePassword() {
    return settingsAction(async () => {
    const old_password = settingsField('personal', 'settingsOldPassword').value;
    const new_password = settingsField('personal', 'settingsNewPassword').value;
    if (new_password !== settingsField('personal', 'settingsConfirmPassword').value) return settingsNotify(t('password.mismatch'), 'error');
    try {
        await settingsRequest('/api/auth/password', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({old_password, new_password})});
        ['settingsOldPassword', 'settingsNewPassword', 'settingsConfirmPassword'].forEach(id => { settingsField('personal', id).value = ''; });
        settingsMarkSaved('personal', ['settingsOldPassword', 'settingsNewPassword', 'settingsConfirmPassword']);
        settingsNotify(t('password.changed'), 'success');
    } catch (error) { settingsNotify(error.message, 'error'); }
    });
}
async function settingsLoadPreferences() {
    try {
        const data = await settingsRequest('/api/user/mail/preferences');
        const box = settingsField('personal', 'settingsPreferences');
        if (!box) return;
        box.innerHTML = `<h3>${t('settings.mailNotifications')}</h3>${data.preferences.map(pref => `<label><input type="checkbox" id="settingsPref_${escapeAttr(pref.event_type)}" data-event-type="${escapeAttr(pref.event_type)}" ${pref.enabled ? 'checked' : ''}>${escapeHtml(t('mailAdmin.event.' + pref.event_type))}</label>${pref.event_type === 'deadline_warning' ? `<input type="number" min="1" max="365" id="settingsDays" value="${Number(pref.days_before) || 2}" aria-label="${escapeAttr(t('settingsOverlay.daysBefore'))}">` : ''}`).join('')}<button class="action-btn primary" id="settingsPreferencesSave">${t('common.save')}</button>`;
        settingsMarkSaved('personal', [...box.querySelectorAll('[id]')].map(el => el.id));
        box.querySelector('button').onclick = () => settingsAction(async () => {
            const preferences = [...box.querySelectorAll('[data-event-type]')].map(input => ({event_type: input.dataset.eventType, enabled: input.checked, days_before: Number(box.querySelector('#settingsDays')?.value) || 2}));
            try {
                await settingsRequest('/api/user/mail/preferences', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({preferences})});
                settingsMarkSaved('personal', [...box.querySelectorAll('[id]')].map(el => el.id));
                settingsNotify(t('mail.prefs.saved'), 'success');
            } catch (error) { settingsNotify(error.message, 'error'); }
        });
    } catch (error) { settingsNotify(error.message, 'error'); }
}
document.addEventListener('DOMContentLoaded', () => {
    const section = new URL(location.href).searchParams.get('settings');
    if (section !== null) openSettingsOverlay(section || 'personal');
});

window.addEventListener('beforeunload', event => {
    if (!settingsState) return;
    const dirtyDialog = settingsState.dialogs.some(overlay => [...settingsValues(overlay)].some(([id,value]) => overlay._baseline.get(id) !== value));
    if (settingsState.busy || dirtyDialog || SETTINGS_SECTIONS.some(section => settingsDirty(section).size)) {
        event.preventDefault(); event.returnValue = '';
    }
});

function settingsNotify(message, type = 'info') {
    if (!settingsState) return showNotification(message, type);
    let notice = settingsState.root.querySelector('[data-settings-notice]');
    if (!notice) {
        notice = document.createElement('div'); notice.dataset.settingsNotice = ''; notice.className = 'settings-notice';
        settingsState.root.querySelector('.settings-dialog>header').after(notice);
    }
    notice.setAttribute('role', type === 'error' ? 'alert' : 'status');
    notice.dataset.type = type; notice.textContent = message;
}

/**
 * Casos Einstellungen - Mail-Tab
 * SMTP-Konfiguration, Testmail, Mail-Vorlagen
 */

let mailConfig = null;
let mailTemplates = [];

// ========================================
// Tab Initialisierung
// ========================================

async function initMailTab() {
    await settingsInitSection('mail', {
        showFilterBar: false,
        loadFn: () => Promise.all([loadMailConfig(), loadMailTemplates()]),
        renderFn: renderMailTab,
    });
}

async function loadMailConfig() {
    mailConfig = await settingsLoadConfig('/api/admin/mail/config');
}

async function loadMailTemplates() {
    const data = await settingsRequest('/api/admin/mail/templates');
    mailTemplates = data.templates || [];
}

// ========================================
// Rendering
// ========================================

function renderMailTab() {
    const container = settingsContainer('mail');
    if (!container) return;

    const hasConfig = !!mailConfig;

    let html = '<div class="mail-container">';

    // Sektion 1: SMTP-Server Konfiguration
    html += renderMailConfigSection(hasConfig);

    // Sektion 2: Testmail (nur wenn Config vorhanden)
    if (hasConfig) {
        html += renderTestMailSection();
    }

    // Sektion 3: Mail-Vorlagen
    if (mailTemplates.length > 0) {
        html += renderTemplatesSection();
    }

    html += '</div>';
    settingsRender('mail', html);
}

function renderMailConfigSection(hasConfig) {
    const c = mailConfig || {};
    const encOptions = ['none', 'starttls', 'ssl'];

    let encSelect = '<select id="mailEncryption">';
    for (const opt of encOptions) {
        const label = opt === 'none' ? t('mailAdmin.encNone') : opt === 'starttls' ? 'STARTTLS' : 'SSL/TLS';
        const sel = (c.encryption || 'starttls') === opt ? 'selected' : '';
        encSelect += `<option value="${opt}" ${sel}>${label}</option>`;
    }
    encSelect += '</select>';

    let html = `
        <div class="mail-section">
            <h3>${t('mailAdmin.smtpTitle')}</h3>
            <div class="mail-form">
                <div class="mail-form-row">
                    <div class="mail-form-field">
                        <label>${t('mailAdmin.smtpServer')}</label>
                        <input type="text" id="mailSmtpServer" value="${escapeAttr(c.smtp_server || '')}"
                               placeholder="smtp.example.com">
                    </div>
                    <div class="mail-form-field" style="max-width:120px">
                        <label>${t('mailAdmin.port')}</label>
                        <input type="number" id="mailSmtpPort" value="${c.smtp_port || 587}">
                    </div>
                    <div class="mail-form-field" style="max-width:140px">
                        <label>${t('mailAdmin.encryption')}</label>
                        ${encSelect}
                    </div>
                </div>
                <div class="mail-form-row">
                    <div class="mail-form-field" style="max-width:100px">
                        <label>${t('mailAdmin.auth')}</label>
                        <label class="mail-checkbox">
                            <input type="checkbox" id="mailAuthEnabled" ${c.auth_enabled !== 0 ? 'checked' : ''}>
                            ${t('mailAdmin.active')}
                        </label>
                    </div>
                    <div class="mail-form-field">
                        <label>${t('auth.username')}</label>
                        <input type="text" id="mailUsername" value="${escapeAttr(c.username || '')}"
                               placeholder="user@example.com">
                    </div>
                    <div class="mail-form-field">
                        <label>${t('auth.password')}</label>
                        <input type="password" id="mailPassword"
                               value="${escapeAttr(c.password || '')}"
                               placeholder="${t('auth.password')}..." autocomplete="new-password">
                    </div>
                </div>
                <div class="mail-form-row">
                    <div class="mail-form-field">
                        <label>${t('mailAdmin.fromAddress')}</label>
                        <input type="email" id="mailFromAddress" value="${escapeAttr(c.from_address || '')}"
                               placeholder="noreply@example.com">
                    </div>
                    <div class="mail-form-field">
                        <label>${t('mailAdmin.fromName')}</label>
                        <input type="text" id="mailFromName" value="${escapeAttr(c.from_name || 'Casos')}"
                               placeholder="Casos">
                    </div>
                </div>
                <div class="mail-form-actions">
                    <button class="action-btn primary" onclick="saveMailConfig()">${t('mailAdmin.testAndSave')}</button>
                    ${hasConfig ? `<button class="action-btn danger" onclick="deleteMailConfig()">${t('common.delete')}</button>` : ''}
                </div>
            </div>`;

    if (hasConfig) {
        const enc = c.encryption === 'ssl' ? 'SSL/TLS' : c.encryption === 'starttls' ? 'STARTTLS' : t('mailAdmin.encNone');
        html += `
            <div class="mail-status-info">
                <strong>${t('mailAdmin.activeConfig')}</strong>
                ${escapeHtml(c.smtp_server)}:${c.smtp_port} | ${enc} | ${t('mailAdmin.fromName')}: ${escapeHtml(c.from_name)} &lt;${escapeHtml(c.from_address)}&gt;
            </div>`;
    }

    html += '</div>';
    return html;
}

function renderTestMailSection() {
    return `
        <div class="mail-section">
            <h3>${t('mailAdmin.testTitle')}</h3>
            <div class="mail-form">
                <div class="mail-form-row">
                    <div class="mail-form-field">
                        <label>${t('mailAdmin.recipient')}</label>
                        <input type="email" id="mailTestRecipient" placeholder="empfaenger@example.com">
                    </div>
                    <div class="mail-form-field" style="max-width:200px;justify-content:flex-end">
                        <button class="action-btn primary" onclick="sendTestMail()">${t('mailAdmin.sendTest')}</button>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderTemplatesSection() {
    const eventLabels = {
        'issue_assigned': t('mailAdmin.event.issue_assigned'),
        'new_update': t('mailAdmin.event.new_update'),
        'status_change': t('mailAdmin.event.status_change'),
        'deadline_reached': t('mailAdmin.event.deadline_reached'),
        'deadline_warning': t('mailAdmin.event.deadline_warning'),
        'invite': t('mailAdmin.event.invite'),
        'test': t('mailAdmin.event.test'),
    };

    const placeholderHints = {
        'issue_assigned': '{recipient_name}, {issue_title}, {actor_name}, {old_assignee}, {new_assignee}, {deadline}, {priority}, {issue_url}',
        'new_update': '{recipient_name}, {issue_title}, {actor_name}, {update_id}, {update_url}, {issue_url}',
        'status_change': '{recipient_name}, {issue_title}, {actor_name}, {old_status}, {new_status}, {issue_url}',
        'deadline_reached': '{recipient_name}, {issue_title}, {issue_url}',
        'deadline_warning': '{recipient_name}, {issue_title}, {days_before}, {deadline}, {issue_url}',
        'invite': '{recipient_name}, {username}, {app_url}',
        'test': t('mailAdmin.noPlaceholders'),
    };

    let html = `<div class="mail-section"><h3>${t('mailAdmin.templates')}</h3>`;
    html += `<div class="mail-status-info" style="margin-bottom: 16px;">${t('mailAdmin.templateAppUrlHint')}</div>`;

    for (const tmpl of mailTemplates) {
        const label = eventLabels[tmpl.event_type] || tmpl.event_type;
        const hint = placeholderHints[tmpl.event_type] || '';

        html += `
            <div class="mail-template-section" data-event-type="${tmpl.event_type}">
                <div class="mail-template-header">
                    <strong>${escapeHtml(label)}</strong>
                    <span class="mail-placeholder-hint">${t('mailAdmin.placeholder')}: ${escapeHtml(hint)}</span>
                </div>
                <div class="mail-form">
                    <div class="mail-form-row">
                        <div class="mail-form-field">
                            <label>${t('mailAdmin.subject')}</label>
                            <input type="text" id="tmplSubject_${tmpl.event_type}" value="${escapeAttr(tmpl.subject)}">
                        </div>
                    </div>
                    <div class="mail-form-row">
                        <div class="mail-form-field">
                            <label>${t('mailAdmin.body')}</label>
                            <textarea id="tmplBody_${tmpl.event_type}" rows="5">${escapeHtml(tmpl.body_text)}</textarea>
                        </div>
                    </div>
                    <div class="mail-form-actions">
                        <button class="action-btn primary" onclick="saveMailTemplate('${tmpl.event_type}')">${t('common.save')}</button>
                    </div>
                </div>
            </div>`;
    }

    html += '</div>';
    return html;
}



// ========================================
// Mail Config CRUD
// ========================================

async function saveMailConfig() {
    return settingsAction(async () => {
    const smtp_server = settingsField('mail', 'mailSmtpServer')?.value?.trim();
    const smtp_port = parseInt(settingsField('mail', 'mailSmtpPort')?.value) || 587;
    const encryption = settingsField('mail', 'mailEncryption')?.value || 'starttls';
    const auth_enabled = settingsField('mail', 'mailAuthEnabled')?.checked ?? true;
    const username = settingsField('mail', 'mailUsername')?.value?.trim() || '';
    const password = settingsField('mail', 'mailPassword')?.value || '';
    const from_address = settingsField('mail', 'mailFromAddress')?.value?.trim();
    const from_name = settingsField('mail', 'mailFromName')?.value?.trim() || 'Casos';

    if (!smtp_server || !from_address) {
        settingsNotify(t('mailAdmin.fillRequired'), 'error');
        return;
    }

    await settingsSaveConfig({
        section: 'mail', fields: ['mailSmtpServer', 'mailSmtpPort', 'mailEncryption', 'mailAuthEnabled', 'mailUsername', 'mailPassword', 'mailFromAddress', 'mailFromName'],
        endpoint: '/api/admin/mail/config',
        data: { smtp_server, smtp_port, encryption, auth_enabled, username, password, from_address, from_name },
        successMessage: t('mailAdmin.saved'),
        onSuccess: async () => {
            await loadMailConfig();
            renderMailTab();
        },
    });
    });
}

async function deleteMailConfig() {
    return settingsAction(async () => {
    await settingsDeleteConfig({
        section: 'mail', fields: ['mailSmtpServer', 'mailSmtpPort', 'mailEncryption', 'mailAuthEnabled', 'mailUsername', 'mailPassword', 'mailFromAddress', 'mailFromName'],
        endpoint: '/api/admin/mail/config',
        confirmMessage: t('mailAdmin.deleteConfirm'),
        successMessage: t('mailAdmin.deleted'),
        onSuccess: () => {
            mailConfig = null;
            renderMailTab();
        },
    });
    });
}

// ========================================
// Testmail
// ========================================

async function sendTestMail() {
    return settingsAction(async () => {
    const to_email = settingsField('mail', 'mailTestRecipient')?.value?.trim();
    if (!to_email) {
        settingsNotify(t('mailAdmin.recipientRequired'), 'error');
        return;
    }

    try {
        const resp = await settingsFetch('/api/admin/mail/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_email }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || t('mailAdmin.sendError'));
        }

        settingsNotify(t('mailAdmin.testSent', { email: to_email }), 'success');
    } catch (error) {
        settingsNotify(error.message, 'error');
    }
    });
}

// ========================================
// Templates
// ========================================

async function saveMailTemplate(eventType) {
    return settingsAction(async () => {
    const subject = settingsField('mail', `tmplSubject_${eventType}`)?.value || '';
    const body_text = settingsField('mail', `tmplBody_${eventType}`)?.value || '';

    if (!subject.trim()) {
        settingsNotify(t('mailAdmin.subjectRequired'), 'error');
        return;
    }

    try {
        const resp = await settingsFetch(`/api/admin/mail/templates/${eventType}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subject, body_text }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || t('common.saveError'));
        }

        settingsMarkSaved('mail', [`tmplSubject_${eventType}`, `tmplBody_${eventType}`]);
        settingsNotify(t('mailAdmin.templateSaved'), 'success');
    } catch (error) {
        settingsNotify(error.message, 'error');
    }
    });
}

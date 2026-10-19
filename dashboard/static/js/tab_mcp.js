/**
 * Casos Einstellungen - MCP-Tab
 * Token-Verwaltung, Audit-Log-Viewer, Kill-Switch.
 */

let mcpConfig = null;
let mcpTokens = [];
let mcpAudit = { items: [], total: 0, limit: 100, offset: 0 };
let mcpAuditFilters = {
    actor_type: '',
    entity_type: '',
    action: '',
};

// ========================================
// Initialisierung
// ========================================

async function initMcpTab() {
    await settingsInitSection('mcp', {
        showFilterBar: false,
        loadFn: loadAllMcpData,
        renderFn: renderMcpTab,
    });
}

async function loadAllMcpData() {
    await Promise.all([
        loadMcpConfig(),
        loadMcpTokens(),
        loadMcpAudit(),
    ]);
}

async function loadMcpConfig() {
    const data = await settingsRequest('/api/admin/mcp/config');
    mcpConfig = data;
}

async function loadMcpTokens() {
    const data = await settingsRequest('/api/admin/mcp/tokens');
    mcpTokens = data.items || [];
}

async function loadMcpAudit() {
    const params = new URLSearchParams();
    params.set('limit', String(mcpAudit.limit));
    params.set('offset', String(mcpAudit.offset));
    if (mcpAuditFilters.actor_type) params.set('actor_type', mcpAuditFilters.actor_type);
    if (mcpAuditFilters.entity_type) params.set('entity_type', mcpAuditFilters.entity_type);
    if (mcpAuditFilters.action) params.set('action', mcpAuditFilters.action);
    const data = await settingsRequest('/api/admin/mcp/audit?' + params.toString());
    mcpAudit = {...mcpAudit, items: data.items || [], total: data.total || 0};
}

// ========================================
// Rendering
// ========================================

function renderMcpTab() {
    const container = settingsContainer('mcp');
    if (!container) return;

    let html = '<div class="ldap-container">';
    html += renderMcpStatusSection();
    html += renderMcpTokensSection();
    html += renderMcpAuditSection();
    html += '</div>';
    settingsRender('mcp', html);

    // Event-Handler nachtraeglich verkabeln
    wireMcpHandlers();
}

function renderMcpStatusSection() {
    const cfg = mcpConfig || { enabled: true, server_url: '', available_tools: [], active_token_count: 0 };
    const enabled = !!cfg.enabled;
    const statusClass = enabled ? 'ldap-status-connected' : '';
    const statusLabel = t(enabled ? 'users.active' : 'users.inactive');
    const toolsHtml = (cfg.available_tools || [])
        .map(t => `<code style="margin-right:6px;display:inline-block">${escapeHtml(t)}</code>`)
        .join(' ');

    return `
        <div class="ldap-section">
            <h3>${t('mcp.server')}</h3>
            <div class="ldap-status-info ${statusClass}">
                <strong>Status:</strong> ${statusLabel}<br>
                <strong>Endpoint:</strong> <code>${escapeHtml(cfg.server_url || t('mcp.unknown'))}</code><br>
                <strong>${t('mcp.dedicatedEndpoint')}:</strong> <code>${escapeHtml(cfg.dedicated_server_url || '')}</code><br>
                <p>${t('mcp.sharedEndpoints')}</p>
                <strong>${t('mcp.activeTokens')}</strong> ${cfg.active_token_count}<br>
                <strong>Tools (${(cfg.available_tools || []).length}):</strong><br>
                <div style="margin-top:6px;line-height:1.8">${toolsHtml}</div>
            </div>
            <div style="margin-top:12px">
                <button id="mcpKillSwitchBtn" class="action-btn ${enabled ? 'danger' : 'primary'}">
                    ${t(enabled ? 'mcp.disable' : 'mcp.enable')}
                </button>
            </div>
        </div>`;
}

function renderMcpTokensSection() {
    let rows = '';
    if (mcpTokens.length === 0) {
        rows = `<tr><td colspan="5" style="text-align:center;opacity:0.6;padding:20px">${t('mcp.noTokens')}</td></tr>`;
    } else {
        for (const token of mcpTokens) {
            const statusBadge = token.active
                ? `<span style="color:var(--color-success, #2e7d32)">${t('users.active')}</span>`
                : `<span style="opacity:0.6">${t('mcp.revoked')} ${escapeHtml(token.revoked_at || '')}</span>`;
            const lastUsed = token.last_used_at ? escapeHtml(token.last_used_at) : `<span style="opacity:0.5">${t('mcp.never')}</span>`;
            const action = token.active
                ? `<button class="action-btn danger" data-revoke="${token.id}">${t('mcp.revoke')}</button>`
                : '';
            rows += `
                <tr>
                    <td>${escapeHtml(token.display_name)}</td>
                    <td>${escapeHtml(token.created_at || '')}</td>
                    <td>${lastUsed}</td>
                    <td>${statusBadge}</td>
                    <td>${action}</td>
                </tr>`;
        }
    }
    return `
        <div class="ldap-section">
            <h3>${t('mcp.tokens')}</h3>
            <div style="margin-bottom:12px">
                <button id="mcpNewTokenBtn" class="action-btn primary">${t('mcp.createToken')}</button>
            </div>
            <table class="admin-table" style="width:100%;border-collapse:collapse">
                <thead>
                    <tr>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.tokenName')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('users.created')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.lastUsed')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">Status</th>
                        <th style="padding:8px;border-bottom:1px solid var(--border-color)"></th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}

function renderMcpAuditSection() {
    const filterOptions = {
        actor_type: ['', 'mcp', 'user', 'system'],
        entity_type: ['', 'issue', 'update', 'attachment', 'user', 'app_config', 'ldap_config', 'tls_config', 'mcp_token', 'mcp_config'],
        action: ['', 'create', 'update', 'delete', 'status_change', 'revoke'],
    };
    const filterLabels = {};
    const mkOpt = (k, val) => {
        const sel = mcpAuditFilters[k] === val ? 'selected' : '';
        const label = val ? (filterLabels[val] || val) : t('mcp.all');
        return `<option value="${escapeHtml(val)}" ${sel}>${escapeHtml(label)}</option>`;
    };

    let rows = '';
    if (mcpAudit.items.length === 0) {
        rows = `<tr><td colspan="6" style="text-align:center;opacity:0.6;padding:20px">${t('mcp.noEntries')}</td></tr>`;
    } else {
        for (const a of mcpAudit.items) {
            const actorBadge = a.actor_type === 'mcp'
                ? '<span style="background:var(--color-primary,#1976d2);color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;margin-right:6px">MCP</span>'
                : (a.actor_type === 'system'
                    ? '<span style="background:#888;color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;margin-right:6px">SYS</span>'
                    : '');
            const actorLabel = (a.actor_display || a.actor_username || t('mcp.unknown'));
            let changesPreview = '';
            if (a.changes_json) {
                try {
                    const parsed = JSON.parse(a.changes_json);
                    changesPreview = JSON.stringify(parsed).slice(0, 80);
                } catch {
                    changesPreview = String(a.changes_json).slice(0, 80);
                }
            }
            rows += `
                <tr>
                    <td style="white-space:nowrap;font-family:monospace;font-size:12px">${escapeHtml(a.timestamp)}</td>
                    <td>${actorBadge}${escapeHtml(actorLabel)}</td>
                    <td>${escapeHtml(a.entity_type)}${a.entity_id ? ' #' + a.entity_id : ''}</td>
                    <td>${escapeHtml(a.action)}</td>
                    <td style="font-family:monospace;font-size:11px;opacity:0.85">${escapeHtml(changesPreview)}</td>
                    <td style="white-space:pre-wrap;overflow-wrap:anywhere;max-width:360px">${escapeHtml(a.reason || '')}</td>
                </tr>`;
        }
    }

    const pageInfo = `${mcpAudit.total ? mcpAudit.offset + 1 : 0}-${Math.min(mcpAudit.offset + mcpAudit.limit, mcpAudit.total)} / ${mcpAudit.total}`;
    const prevDisabled = mcpAudit.offset === 0 ? 'disabled' : '';
    const nextDisabled = (mcpAudit.offset + mcpAudit.limit) >= mcpAudit.total ? 'disabled' : '';

    return `
        <div class="ldap-section">
            <h3>${t('mcp.audit')}</h3>
            <div style="display:flex;gap:12px;margin-bottom:12px;align-items:flex-end;flex-wrap:wrap">
                <div>
                    <label style="display:block;font-size:12px;opacity:0.7">${t('mcp.actorType')}</label>
                    <select id="auditFilterActor">${filterOptions.actor_type.map(v => mkOpt('actor_type', v)).join('')}</select>
                </div>
                <div>
                    <label style="display:block;font-size:12px;opacity:0.7">${t('mcp.entity')}</label>
                    <select id="auditFilterEntity">${filterOptions.entity_type.map(v => mkOpt('entity_type', v)).join('')}</select>
                </div>
                <div>
                    <label style="display:block;font-size:12px;opacity:0.7">${t('mcp.action')}</label>
                    <select id="auditFilterAction">${filterOptions.action.map(v => mkOpt('action', v)).join('')}</select>
                </div>
                <button id="auditApplyFiltersBtn" class="action-btn">${t('mcp.filter')}</button>
            </div>
            <table class="admin-table" style="width:100%;border-collapse:collapse">
                <thead>
                    <tr>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.time')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.actor')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.entity')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.action')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.changes')}</th>
                        <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border-color)">${t('mcp.auditReason')}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
                <button id="auditPrevBtn" class="action-btn" ${prevDisabled}>${t('mcp.previous')}</button>
                <span style="opacity:0.7;font-size:13px">${pageInfo}</span>
                <button id="auditNextBtn" class="action-btn" ${nextDisabled}>${t('mcp.next')}</button>
            </div>
        </div>`;
}

// ========================================
// Event-Handling
// ========================================

function wireMcpHandlers() {
    const killBtn = settingsField('mcp', 'mcpKillSwitchBtn');
    if (killBtn) killBtn.addEventListener('click', toggleMcpEnabled);

    const newTokenBtn = settingsField('mcp', 'mcpNewTokenBtn');
    if (newTokenBtn) newTokenBtn.addEventListener('click', openNewTokenModal);

    settingsContainer('mcp').querySelectorAll('[data-revoke]').forEach(btn => {
        btn.addEventListener('click', () => revokeToken(parseInt(btn.dataset.revoke, 10)));
    });

    const applyBtn = settingsField('mcp', 'auditApplyFiltersBtn');
    if (applyBtn) applyBtn.addEventListener('click', applyAuditFilters);

    const prevBtn = settingsField('mcp', 'auditPrevBtn');
    if (prevBtn) prevBtn.addEventListener('click', () => paginateAudit(-1));
    const nextBtn = settingsField('mcp', 'auditNextBtn');
    if (nextBtn) nextBtn.addEventListener('click', () => paginateAudit(1));
}

async function toggleMcpEnabled() {
    return settingsAction(async () => {
    if (!mcpConfig) return;
    const next = !mcpConfig.enabled;
    const confirmMsg = next
        ? t('mcp.enableConfirm')
        : t('mcp.disableConfirm');
    if (!await settingsConfirm(confirmMsg)) return;
    try {
        const resp = await settingsFetch('/api/admin/mcp/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: next }),
        });
        if (!resp.ok) throw new Error(t('common.saveError'));
        settingsNotify(t(next ? 'mcp.enabled' : 'mcp.disabled'), 'success');
        await loadMcpConfig();
        renderMcpTab();
    } catch (e) {
        settingsNotify(e.message || t('common.error'), 'error');
    }
    });
}

function openNewTokenModal() {
    settingsCreateModal({
        title: t('mcp.createToken'),
        body: `
            <div class="modal-field" style="margin-bottom:12px">
                <label for="mcpNewTokenName" style="display:block;margin-bottom:4px">
                    ${t('mcp.tokenName')}
                </label>
                <input type="text" id="mcpNewTokenName" style="width:100%" autocomplete="off">
            </div>
            <p style="opacity:0.75;font-size:12px;margin:0">
                ${t('mcp.onceHint')}
            </p>`,
        footer: `
            <button class="action-btn" onclick="settingsCloseModal()">${t('common.cancel')}</button>
            <button class="action-btn primary" id="mcpCreateTokenBtn">${t('common.create')}</button>`,
        onOpen: () => {
            const input = settingsField('mcp', 'mcpNewTokenName');
            if (input) input.focus();
            const btn = settingsField('mcp', 'mcpCreateTokenBtn');
            if (btn) btn.addEventListener('click', createTokenSubmit);
        },
    });
}

async function createTokenSubmit() {
    return settingsAction(async () => {
    const nameInput = settingsField('mcp', 'mcpNewTokenName');
    const name = (nameInput && nameInput.value || '').trim();
    if (!name) {
        settingsNotify(t('mcp.nameRequired'), 'error');
        return;
    }
    try {
        const resp = await settingsFetch('/api/admin/mcp/tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: name }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || t('common.createError'));
        await settingsCloseModal(true);
        showTokenOnce(data);
        await loadMcpTokens();
        await loadMcpConfig();
        renderMcpTab();
    } catch (e) {
        settingsNotify(e.message || t('common.error'), 'error');
    }
    });
}

function showTokenOnce(data) {
    const tokenStr = data.token || '';
    settingsCreateModal({
        title: t('mcp.tokenCreated'),
        body: `
            <p style="margin:0 0 12px">
                ${t('mcp.onceHint')}
            </p>
            <textarea id="mcpTokenView" readonly
                style="width:100%;min-height:80px;font-family:monospace;font-size:13px"
                onclick="this.select()">${escapeHtml(tokenStr)}</textarea>
            <p style="margin:12px 0 0;font-size:12px;opacity:0.75">
                ${t('mcp.connectionConfig')}
            </p>
            <pre style="background:var(--bg-secondary,#f5f5f5);padding:8px;border-radius:4px;font-size:11px;overflow:auto">{
  "mcpServers": {
    "casos": {
      "type": "http",
      "url": "${escapeHtml((mcpConfig && (mcpConfig.dedicated_server_url || mcpConfig.server_url)) || 'http://localhost:8516/mcp/')}",
      "headers": { "Authorization": "Bearer ${escapeHtml(tokenStr)}" }
    }
  }
}</pre>`,
        footer: `
            <button class="action-btn" onclick="copyTokenToClipboard()">${t('mcp.copyToken')}</button>
            <button class="action-btn primary" onclick="settingsCloseModal()">${t('common.close')}</button>`,
        cssClass: 'modal-wide',
        closeOnBackdrop: false,
        closeOnEscape: false,
    });
}

async function copyTokenToClipboard() {
    const ta = settingsField('mcp', 'mcpTokenView');
    if (!ta) return;
    ta.select();
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(ta.value);
        } else {
            document.execCommand('copy');
        }
        settingsNotify(t('mcp.copied'), 'success');
    } catch (e) {
        settingsNotify(t('mcp.copyFailed'), 'error');
    }
}

async function revokeToken(tokenId) {
    return settingsAction(async () => {
    if (!await settingsConfirm(t('mcp.revokeConfirm'))) return;
    try {
        const resp = await settingsFetch('/api/admin/mcp/tokens/' + tokenId, { method: 'DELETE' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || t('common.error'));
        }
        settingsNotify(t('mcp.revoked'), 'success');
        await loadMcpTokens();
        await loadMcpConfig();
        renderMcpTab();
    } catch (e) {
        settingsNotify(e.message || t('common.error'), 'error');
    }
    });
}

async function applyAuditFilters() {
    try {
    mcpAuditFilters.actor_type = settingsField('mcp', 'auditFilterActor').value;
    mcpAuditFilters.entity_type = settingsField('mcp', 'auditFilterEntity').value;
    mcpAuditFilters.action = settingsField('mcp', 'auditFilterAction').value;
    mcpAudit.offset = 0;
    await loadMcpAudit();
    renderMcpTab();
    } catch(error) { settingsNotify(error.message, 'error'); }
}

async function paginateAudit(direction) {
    try {
    const newOffset = mcpAudit.offset + direction * mcpAudit.limit;
    if (newOffset < 0) return;
    if (newOffset >= mcpAudit.total) return;
    mcpAudit.offset = newOffset;
    await loadMcpAudit();
    renderMcpTab();
    } catch(error) { settingsNotify(error.message, 'error'); }
}

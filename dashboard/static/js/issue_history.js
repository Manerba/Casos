/* Issue events and human updates; refresh only this slot, preserving editor drafts. */
(() => {
    'use strict';
    let active = null;
    const tr = key => t(`history.${key}`);
    const esc = value => escapeHtml(String(value ?? ''));
    const dateTime = value => {
        const parsed = new Date(value.replace(' ', 'T') + (/[zZ]|[+-]\d\d:\d\d$/.test(value) ? '' : 'Z'));
        return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(getLang());
    };
    function render(state) {
        const { slot, items } = state;
        slot.innerHTML = `<div class="issue-history-heading"><h3>${tr('title')}</h3><button type="button" class="issue-btn" data-history-refresh>${tr('refresh')}</button></div><p role="alert" class="issue-history-error" hidden></p><ol class="issue-history-list">${items.map(item => {
            let content;
            if (item.kind === 'update') {
                content = `<a href="/issues/${state.issueId}?update=${item.update_id}" data-history-update="${item.update_id}">${tr('update')} #${item.update_id}</a><p class="issue-history-preview">${esc(item.content_preview)}</p>`;
            } else {
                const assignment = item.event_type === 'assignment';
                const old = assignment ? (item.old_value === null ? tr('unassigned') : item.old_label || `#${item.old_value}`) : t(`status.${item.old_value}`);
                const next = assignment ? (item.new_value === null ? tr('unassigned') : item.new_label || `#${item.new_value}`) : t(`status.${item.new_value}`);
                content = `<span>${tr(assignment ? 'assignment' : 'status')}: <span class="issue-history-old">${esc(old)}</span> <span aria-label="${tr('to')}">→</span> <strong>${esc(next)}</strong></span>`;
            }
            return `<li data-history-kind="${item.kind}" data-history-id="${item.id}"><div class="issue-history-meta"><strong>${esc(item.actor_name || tr('unknownActor'))}</strong><time>${esc(dateTime(item.created_at))}</time></div><div>${content}</div></li>`;
        }).join('')}</ol>${items.length ? '' : `<p class="issue-empty">${tr('empty')}</p>`}<button type="button" class="issue-btn" data-history-more ${state.next === null ? 'hidden' : ''}>${tr('older')}</button>`;
        slot.querySelector('[data-history-refresh]').onclick = () => load(state, false);
        slot.querySelector('[data-history-more]').onclick = () => load(state, true);
        slot.querySelectorAll('[data-history-update]').forEach(link => link.onclick = event => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
            event.preventDefault(); openUpdateDialog(state.issueId, Number(link.dataset.historyUpdate));
        });
    }
    async function load(state, append) {
        const sequence = ++state.request;
        state.slot.querySelectorAll('button').forEach(button => button.disabled = true);
        try {
            const offset = append ? state.next : 0;
            const response = await fetch(`/api/issues/${state.issueId}/history?offset=${offset}&limit=50`);
            const data = await response.json();
            if (!response.ok) {
                const detail = typeof data.detail === 'string' ? data.detail : tr('loadError');
                throw new Error(/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)+$/.test(detail) ? t(detail) : detail);
            }
            if (state !== active || !state.slot.isConnected || sequence !== state.request) return;
            state.items = append ? [...new Map([...state.items, ...data.items].map(item => [`${item.kind}-${item.id}`, item])).values()] : data.items;
            state.next = data.next_offset;
            render(state);
        } catch (error) {
            if (state !== active || !state.slot.isConnected || sequence !== state.request) return;
            const panel = state.slot.querySelector('.issue-history-error');
            panel.textContent = error.message || tr('loadError'); panel.hidden = false;
            state.slot.querySelectorAll('button').forEach(button => button.disabled = false);
        }
    }
    window.addEventListener('issue-detail-rendered', event => {
        const { issueId, historySlot } = event.detail;
        if (!historySlot?.isConnected) return;
        active = { issueId, slot: historySlot, items: [], next: null, request: 0 };
        historySlot.hidden = false;
        render(active); load(active, false);
    });
    for (const name of ['issue-changed', 'update-saved', 'issue-history-changed']) {
        window.addEventListener(name, event => {
            if (active?.issueId === event.detail.issueId && active.slot.isConnected) load(active, false);
        });
    }
})();

/** Flat Issue list/detail UI. Services remain the authority for every action. */
(function () {
    'use strict';
    const statuses = ['offen', 'in_arbeit', 'erledigt', 'abgebrochen'];
    const state = {
        users: [], issueId: null, issue: null, generation: 0,
        list: { status: '', assignee: '', sortBy: 'id', direction: 'desc', offset: 0, limit: 25, scroll: 0, requestSequence: 0 },
        updates: [], attachments: [], updateRequest: 0, attachmentRequest: 0,
        uploading: new Set(), dialogs: new Set(), descriptionSaves: new Map(),
    };
    const main = () => document.getElementById('contentContainer');
    const tr = (key, values) => t(`issues.${key}`, values);
    const esc = value => escapeHtml(value);
    const attr = value => escapeAttr(value);
    const errorText = error => /^(description|updates|issues)\./.test(error?.message || '') ? t(error.message) : (error?.message || t('common.error'));
    const userLabel = user => [user?.vorname, user?.nachname].filter(Boolean).join(' ').trim() || user?.username || tr('unknownUser');
    const userName = id => id === null ? tr('unassigned') : userLabel(state.users.find(user => user.id === id) || { username: `#${id}` });
    const dateTime = value => {
        if (!value) return '—';
        const date = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : value.replace(' ', 'T') + 'Z');
        return Number.isNaN(date.getTime()) ? value : date.toLocaleString(getLang());
    };
    const sizeLabel = size => size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KiB` : `${(size / 1024 / 1024).toFixed(1)} MiB`;

    async function request(url, options = {}) {
        let response;
        try { response = await fetch(url, options); }
        catch { throw new Error(tr('connectionError')); }
        let data;
        try { data = await response.json(); }
        catch { throw new Error(tr('responseError')); }
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : t('common.saveError'));
        return data;
    }
    const jsonOptions = (method, data) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const current = (id, generation) => state.issueId === id && state.generation === generation;

    function showPageError(error) {
        main().innerHTML = `<div class="issue-empty" role="alert">${esc(errorText(error))}</div><button class="issue-btn" data-issue-retry>${tr('retry')}</button>`;
        main().querySelector('[data-issue-retry]').onclick = () => window.renderIssueRoute(parseRoute());
    }

    function userOptions(selected = null, includeAll = false) {
        const first = includeAll ? `<option value="">${t('common.all')}</option><option value="unassigned">${tr('unassigned')}</option>`
            : `<option value="">${tr('unassigned')}</option>`;
        const missing = selected !== null && !state.users.some(user => user.id === selected)
            ? `<option value="${selected}" selected>#${selected}</option>` : '';
        return first + missing + state.users.map(user => `<option value="${user.id}" ${user.id === selected ? 'selected' : ''}>${esc(userLabel(user))}</option>`).join('');
    }

    function buildFilters() {
        const bar = document.getElementById('filterBar');
        bar.innerHTML = `<label class="issue-filter">${tr('status')}<select id="issue-status-filter"><option value="">${t('common.all')}</option>${statuses.map(value => `<option value="${value}">${t(`status.${value}`)}</option>`).join('')}</select></label>
            <label class="issue-filter">${tr('assignee')}<select id="issue-assignee-filter">${userOptions(null, true)}</select></label>
            <label class="issue-filter">${tr('sort')}<select id="issue-sort-filter">${['id', 'title', 'priority', 'deadline', 'created_at'].map(value => `<option value="${value}">${tr(value === 'created_at' ? 'created' : value)}</option>`).join('')}</select></label>
            <label class="issue-filter">${tr('direction')}<select id="issue-direction-filter"><option value="desc">${tr('descending')}</option><option value="asc">${tr('ascending')}</option></select></label>`;
        const controls = [['issue-status-filter', 'status'], ['issue-assignee-filter', 'assignee'], ['issue-sort-filter', 'sortBy'], ['issue-direction-filter', 'direction']];
        for (const [id, property] of controls) {
            const control = document.getElementById(id);
            control.value = state.list[property];
            control.onchange = () => { state.list[property] = control.value; state.list.offset = 0; state.list.scroll = 0; loadList(state.generation); };
        }
        bar.style.display = 'flex';
    }

    async function loadList(generation) {
        const options = state.list;
        const params = new URLSearchParams({ offset: options.offset, limit: options.limit, sort_by: options.sortBy, sort_direction: options.direction });
        if (options.status) params.set('status', options.status);
        if (options.assignee === 'unassigned') params.set('unassigned', 'true');
        else if (options.assignee) params.set('assigned_to', options.assignee);
        const sequence = ++state.list.requestSequence;
        main().innerHTML = `<p class="issue-empty">${t('common.loading')}</p>`;
        try {
            const data = await request(`/api/issues?${params}`);
            if (!current(null, generation) || sequence !== state.list.requestSequence) return;
            if (!data.items.length && options.offset > 0 && data.total > 0) {
                options.offset = Math.max(0, Math.floor((data.total - 1) / options.limit) * options.limit);
                return loadList(generation);
            }
            main().innerHTML = `<section class="issues-list">
                <div class="issue-page-heading"><h2>${tr('list')}</h2><button type="button" class="issue-btn primary" id="issue-create">+ ${tr('new')}</button></div>
                <div id="issue-search-slot"></div>
                <div class="issue-table-wrap"><table class="issue-table"><thead><tr>${['id', 'title', 'status', 'priority', 'assignee', 'deadline', 'created'].map(key => `<th scope="col">${tr(key)}</th>`).join('')}</tr></thead>
                <tbody>${data.items.map(issue => `<tr data-issue-id="${issue.id}">
                    <td data-label="${attr(tr('id'))}">#${issue.id}</td>
                    <td data-label="${attr(tr('title'))}"><a class="issue-link" href="/issues/${issue.id}">${esc(issue.title)}</a></td>
                    <td data-label="${attr(tr('status'))}"><span class="issue-status status-${issue.status}">${t(`status.${issue.status}`)}</span></td>
                    <td data-label="${attr(tr('priority'))}">${issue.priority}</td>
                    <td data-label="${attr(tr('assignee'))}">${esc(userName(issue.assigned_to))}</td>
                    <td data-label="${attr(tr('deadline'))}">${esc(issue.deadline || '—')}</td>
                    <td data-label="${attr(tr('created'))}">${esc(dateTime(issue.created_at))}</td>
                </tr>`).join('')}</tbody></table></div>
                ${data.items.length ? '' : `<p class="issue-empty">${tr('empty')}</p>`}
                <nav class="issue-pagination" aria-label="${attr(tr('pagination'))}"><button class="issue-btn" id="issue-prev" ${options.offset === 0 ? 'disabled' : ''}>${tr('previous')}</button>
                    <span>${tr('pageSummary', { from: data.total ? options.offset + 1 : 0, to: options.offset + data.items.length, total: data.total })}</span>
                    <button class="issue-btn" id="issue-next" ${data.next_offset === null ? 'disabled' : ''}>${tr('next')}</button></nav></section>`;
            document.getElementById('issue-create').onclick = () => openIssueForm();
            main().querySelectorAll('.issue-link').forEach(link => link.addEventListener('click', event => {
                if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                navigateIssue(Number(link.closest('[data-issue-id]').dataset.issueId));
            }));
            document.getElementById('issue-prev').onclick = () => { options.offset = Math.max(0, options.offset - options.limit); options.scroll = 0; loadList(generation); };
            document.getElementById('issue-next').onclick = () => { options.offset = data.next_offset; options.scroll = 0; loadList(generation); };
            window.dispatchEvent(new CustomEvent('issue-list-rendered', { detail: { container: document.getElementById('issue-search-slot') } }));
            requestAnimationFrame(() => { if (current(null, generation)) window.scrollTo(0, options.scroll); });
        } catch (error) { if (current(null, generation) && sequence === state.list.requestSequence) showPageError(error); }
    }

    function metadataMarkup(issue) {
        return `<div class="issue-page-heading"><div><span class="issue-id">#${issue.id}</span><h2>${esc(issue.title)}</h2></div><div class="issue-actions">
            ${issue.permissions.can_edit ? `<button class="issue-btn" id="issue-edit">${tr('editDetails')}</button>` : ''}
            ${issue.permissions.can_manage ? `<button class="issue-btn" id="issue-editors">${tr('editors')}</button><button class="issue-btn danger" id="issue-delete">${t('common.delete')}</button>` : ''}</div></div>
            <dl class="issue-metadata">
            ${[['status', t(`status.${issue.status}`)], ['priority', issue.priority], ['assignee', userName(issue.assigned_to)], ['deadline', issue.deadline || '—'], ['creator', issue.created_by === null ? tr('unknownUser') : userName(issue.created_by)], ['created', dateTime(issue.created_at)], ['updated', dateTime(issue.updated_at)]].map(([key, value]) => `<div><dt>${tr(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}
            </dl>`;
    }

    async function loadDetail(issueId, generation) {
        main().innerHTML = `<p class="issue-empty">${t('common.loading')}</p>`;
        try {
            // A refresh must read after its own in-flight description write.
            // Otherwise an older GET snapshot could replace the successful save.
            await state.descriptionSaves.get(issueId)?.catch(() => {});
            const issue = await request(`/api/issues/${issueId}`);
            if (!current(issueId, generation)) return;
            state.issue = issue;
            state.updates = [];
            state.attachments = [];
            main().innerHTML = `<article class="issue-detail" data-issue-id="${issueId}">
                <a class="issue-back" href="/">← ${tr('back')}</a>
                <section id="issue-metadata-panel">${metadataMarkup(issue)}</section>
                <section class="issue-panel issue-description-panel"><h3>${tr('description')}</h3><div id="issue-description-${issueId}"></div><div id="issue-description-retained"></div></section>
                <div class="issue-columns">
                    <section class="issue-panel" id="issue-updates-panel"><div class="issue-section-heading"><h3>${tr('updates')}</h3><button class="issue-btn" id="issue-add-update" hidden>${t('updates.add')}</button></div><p class="issue-section-error" role="alert" hidden></p><div id="issue-updates"></div><button class="issue-btn issue-more" id="issue-more-updates" hidden>${tr('olderUpdates')}</button></section>
                    <section class="issue-panel" id="issue-attachments-panel"><div class="issue-section-heading"><h3>${tr('attachments')}</h3><button class="issue-btn" id="issue-attach" hidden>${tr('attach')}</button></div><input type="file" id="issue-attachment-file" hidden><p id="issue-upload-status" role="status" hidden></p><button class="issue-btn" id="issue-upload-retry" hidden>${tr('retry')}</button><p class="issue-section-error" role="alert" hidden></p><div id="issue-attachments"></div><button class="issue-btn issue-more" id="issue-more-attachments" hidden>${tr('moreAttachments')}</button></section>
                </div>
                <section class="issue-panel" id="issue-history-slot" data-issue-id="${issueId}" hidden></section>
            </article>`;
            main().querySelector('.issue-back').onclick = event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigateIssue(null); } };
            bindMetadata(issue);
            const editorId = `issue-description-${issueId}`;
            new MarkdownEditor(editorId, issue.description, {
                label: tr('description'), format: issue.description_format, revision: issue.description_revision,
                readOnly: !issue.permissions.can_edit, saveErrorMessage: errorText,
                onSave: async (description, revision) => {
                    const save = request(`/api/issues/${issueId}`, jsonOptions('PUT', { description, description_revision: revision }));
                    state.descriptionSaves.set(issueId, save);
                    try {
                        const result = await save;
                        return { ...result, revision: result.description_revision };
                    } finally {
                        if (state.descriptionSaves.get(issueId) === save) state.descriptionSaves.delete(issueId);
                    }
                },
                onSaved: (source, result) => {
                    issue.description = source;
                    issue.description_revision = result.description_revision;
                    if (state.issue?.id === issueId) Object.assign(state.issue, result);
                },
            });
            if (!issue.permissions.can_edit && MarkdownEditor.drafts.has(editorId)) {
                const retained = document.getElementById('issue-description-retained');
                retained.innerHTML = `<p>${tr('retainedDraft')}</p><textarea readonly aria-label="${attr(tr('retainedDraft'))}"></textarea>`;
                retained.querySelector('textarea').value = MarkdownEditor.drafts.get(editorId);
            }
            document.getElementById('issue-add-update').onclick = () => openUpdateDialog(issueId);
            setupUpload(issueId, generation);
            await Promise.allSettled([loadUpdates(issueId, false), loadAttachments(issueId, false)]);
            if (current(issueId, generation)) window.dispatchEvent(new CustomEvent('issue-detail-rendered', { detail: { issueId, issue, historySlot: document.getElementById('issue-history-slot') } }));
        } catch (error) { if (current(issueId, generation)) showPageError(error); }
    }

    function bindMetadata(issue) {
        document.getElementById('issue-edit')?.addEventListener('click', () => openIssueForm(issue));
        document.getElementById('issue-editors')?.addEventListener('click', () => openEditors(issue.id));
        document.getElementById('issue-delete')?.addEventListener('click', async event => {
            if (!window.confirm(tr('deleteIssueConfirm'))) return;
            event.currentTarget.disabled = true;
            try {
                await request(`/api/issues/${issue.id}`, { method: 'DELETE' });
                MarkdownEditor.drafts.delete(`issue-description-${issue.id}`);
                MarkdownEditor.draftRevisions.delete(`issue-description-${issue.id}`);
                navigateIssue(null);
            } catch (error) { showNotification(errorText(error), 'error'); if (event.target.isConnected) event.target.disabled = false; }
        });
    }

    function sectionError(id, error) {
        const panel = document.getElementById(id);
        const box = panel?.querySelector('.issue-section-error');
        if (box) { box.textContent = errorText(error); box.hidden = false; }
    }

    function previewText(content, format) {
        const node = document.createElement('div');
        node.innerHTML = renderMarkdown(content || '', format);
        return (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240);
    }

    async function loadUpdates(issueId, append) {
        const generation = state.generation, sequence = ++state.updateRequest;
        const offset = append ? state.updates.length : 0;
        try {
            const data = await request(`/api/issues/${issueId}/updates?offset=${offset}&limit=50`);
            if (!current(issueId, generation) || sequence !== state.updateRequest) return;
            state.updates = append ? [...new Map([...state.updates, ...data.items].map(item => [item.id, item])).values()] : data.items;
            document.querySelector('#issue-updates-panel .issue-section-error').hidden = true;
            document.getElementById('issue-add-update').hidden = !data.can_create;
            const list = document.getElementById('issue-updates');
            list.innerHTML = state.updates.length ? state.updates.map(entry => `<div class="issue-update-card" data-update-id="${entry.id}"><button class="issue-update-open" type="button" aria-haspopup="dialog"><span class="issue-update-meta"><strong>#${entry.id} ${esc(entry.user_name || t('updates.unknownAuthor'))}</strong><time>${esc(dateTime(entry.created_at))}</time></span><span class="issue-update-preview">${esc(previewText(entry.content, entry.content_format))}</span></button>${entry.can_delete ? `<button type="button" class="issue-btn danger" data-delete-update="${entry.id}" aria-label="${attr(tr('deleteUpdate'))}">${t('common.delete')}</button>` : ''}</div>`).join('') : `<p class="issue-empty">${tr('noUpdates')}</p>`;
            list.querySelectorAll('.issue-update-open').forEach(button => button.onclick = () => openUpdateDialog(issueId, Number(button.closest('[data-update-id]').dataset.updateId)));
            list.querySelectorAll('[data-delete-update]').forEach(button => button.onclick = async () => {
                if (!window.confirm(tr('deleteUpdateConfirm'))) return;
                button.disabled = true;
                try {
                    await request(`/api/issues/${issueId}/updates/${button.dataset.deleteUpdate}`, { method: 'DELETE' });
                    await loadUpdates(issueId, false);
                    window.dispatchEvent(new CustomEvent('issue-history-changed', { detail: { issueId } }));
                }
                catch (error) { if (current(issueId, generation)) sectionError('issue-updates-panel', error); button.disabled = false; }
            });
            const more = document.getElementById('issue-more-updates');
            more.textContent = tr('olderUpdates');
            more.hidden = data.next_offset === null;
            more.disabled = false;
            more.onclick = () => { more.disabled = true; loadUpdates(issueId, true); };
        } catch (error) {
            if (current(issueId, generation) && sequence === state.updateRequest) {
                sectionError('issue-updates-panel', error);
                const more = document.getElementById('issue-more-updates');
                more.hidden = false; more.disabled = false; more.textContent = tr('retry');
                more.onclick = () => loadUpdates(issueId, append);
            }
        }
    }

    async function loadAttachments(issueId, append) {
        const generation = state.generation, sequence = ++state.attachmentRequest;
        const offset = append ? state.attachments.length : 0;
        try {
            const data = await request(`/api/issues/${issueId}/attachments?offset=${offset}&limit=50`);
            if (!current(issueId, generation) || sequence !== state.attachmentRequest) return;
            state.attachments = append ? [...new Map([...state.attachments, ...data.items].map(item => [item.id, item])).values()] : data.items;
            document.querySelector('#issue-attachments-panel .issue-section-error').hidden = true;
            document.getElementById('issue-attach').hidden = !data.can_upload;
            const list = document.getElementById('issue-attachments');
            list.innerHTML = state.attachments.length ? state.attachments.map(entry => `<div class="issue-attachment" data-attachment-id="${entry.id}"><div class="issue-attachment-info"><strong>${esc(entry.original_name)}</strong><span>${esc(sizeLabel(entry.size))} · ${esc(entry.uploader_name || tr('unknownUser'))} · ${esc(dateTime(entry.created_at))}</span></div><div class="issue-actions"><button class="issue-btn" data-preview-attachment="${entry.id}" ${typeof window.openAttachmentPreview === 'function' ? '' : 'hidden'}>${tr('preview')}</button><a class="issue-btn" href="${attr(entry.download_url)}" download>${tr('download')}</a>${entry.can_delete ? `<button class="issue-btn danger" data-delete-attachment="${entry.id}">${t('common.delete')}</button>` : ''}</div></div>`).join('') : `<p class="issue-empty">${tr('noAttachments')}</p>`;
            list.querySelectorAll('[data-preview-attachment]').forEach(button => button.onclick = () => window.openAttachmentPreview?.(issueId, Number(button.dataset.previewAttachment)));
            list.querySelectorAll('[data-delete-attachment]').forEach(button => button.onclick = async () => {
                if (!window.confirm(tr('deleteAttachmentConfirm'))) return;
                button.disabled = true;
                try { await request(`/api/issues/${issueId}/attachments/${button.dataset.deleteAttachment}`, { method: 'DELETE' }); await loadAttachments(issueId, false); }
                catch (error) { if (current(issueId, generation)) sectionError('issue-attachments-panel', error); button.disabled = false; }
            });
            const more = document.getElementById('issue-more-attachments');
            more.textContent = tr('moreAttachments');
            more.hidden = data.next_offset === null;
            more.disabled = false;
            more.onclick = () => { more.disabled = true; loadAttachments(issueId, true); };
        } catch (error) {
            if (current(issueId, generation) && sequence === state.attachmentRequest) {
                sectionError('issue-attachments-panel', error);
                const more = document.getElementById('issue-more-attachments');
                more.hidden = false; more.disabled = false; more.textContent = tr('retry');
                more.onclick = () => loadAttachments(issueId, append);
            }
        }
    }

    function setupUpload(issueId, generation) {
        const input = document.getElementById('issue-attachment-file');
        const button = document.getElementById('issue-attach');
        const retry = document.getElementById('issue-upload-retry');
        const status = document.getElementById('issue-upload-status');
        let selected = null;
        button.onclick = () => { input.value = ''; input.click(); };
        const upload = async () => {
            if (!selected || button.disabled) return;
            if (selected.size > 500 * 1024 * 1024) { sectionError('issue-attachments-panel', new Error(tr('uploadLimit'))); return; }
            const work = {};
            state.uploading.add(work);
            button.disabled = true; retry.hidden = true; status.hidden = false;
            status.textContent = tr('uploading', { name: selected.name });
            try {
                const data = new FormData(); data.append('file', selected);
                await request(`/api/issues/${issueId}/attachments`, { method: 'POST', body: data });
                selected = null;
                if (current(issueId, generation)) { status.hidden = true; await loadAttachments(issueId, false); }
            } catch (error) {
                if (current(issueId, generation)) { status.hidden = true; sectionError('issue-attachments-panel', error); retry.hidden = false; }
            } finally { state.uploading.delete(work); button.disabled = false; }
        };
        input.onchange = () => { selected = input.files[0] || null; upload(); };
        retry.onclick = upload;
    }

    function formDialog(title, body, save, success) {
        const priorFocus = document.activeElement;
        const dialog = document.createElement('dialog');
        dialog.className = 'issue-form-dialog';
        const titleId = `issue-form-title-${Date.now()}-${state.dialogs.size}`;
        dialog.setAttribute('aria-labelledby', titleId);
        dialog.innerHTML = `<form><header><h2 id="${titleId}">${esc(title)}</h2><button class="issue-btn" type="button" data-close>${t('common.close')}</button></header><div class="issue-form-body">${body}</div><p class="issue-form-error" role="alert" hidden></p><footer><button class="issue-btn" type="button" data-cancel>${t('common.cancel')}</button><button class="issue-btn primary" type="submit">${t('common.save')}</button></footer></form>`;
        const form = dialog.querySelector('form');
        let busy = false;
        const snapshot = () => JSON.stringify([...form.elements].filter(el => el.name).map(el => [el.name, el.type === 'checkbox' ? el.checked : el.value]));
        const initial = snapshot();
        const dirty = () => snapshot() !== initial;
        const close = (saved = false) => {
            if (busy) return false;
            if (!saved && dirty() && !window.confirm(tr('discard'))) return false;
            state.dialogs.delete(dialog); dialog.close(); dialog.remove();
            if (priorFocus?.isConnected) priorFocus.focus();
            return true;
        };
        dialog._isDirty = dirty;
        dialog._isBusy = () => busy;
        dialog.querySelector('[data-close]').onclick = () => close();
        dialog.querySelector('[data-cancel]').onclick = () => close();
        dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
        dialog.addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
            if (event.key === 'Tab') {
                const focusable = [...dialog.querySelectorAll('button, input, select, textarea, a[href]')].filter(el => !el.disabled && el.getClientRects().length);
                const first = focusable[0], last = focusable.at(-1);
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        });
        form.onsubmit = async event => {
            event.preventDefault();
            if (busy || !form.reportValidity()) return;
            busy = true;
            const controls = [...form.elements], oldDisabled = controls.map(el => el.disabled);
            controls.forEach(el => el.disabled = true);
            const error = dialog.querySelector('.issue-form-error'); error.hidden = true;
            try {
                const result = await save(form);
                busy = false;
                close(true);
                await success?.(result);
            } catch (failure) { error.textContent = errorText(failure); error.hidden = false; }
            finally { busy = false; controls.forEach((el, index) => el.disabled = oldDisabled[index]); }
        };
        state.dialogs.add(dialog); document.body.appendChild(dialog); dialog.showModal();
        (form.querySelector('input:not([type=checkbox]), select, textarea') || dialog.querySelector('[data-close]')).focus();
        return dialog;
    }

    function openIssueForm(issue = null) {
        const creating = issue === null;
        const value = issue || { title: '', status: 'offen', priority: 50, deadline: null, assigned_to: null };
        const canAssign = creating || issue.permissions.can_manage;
        const body = `<label>${tr('title')}<input name="title" required maxlength="500" value="${attr(value.title)}"></label>
            <div class="issue-form-grid"><label>${tr('status')}<select name="status">${statuses.map(status => `<option value="${status}" ${value.status === status ? 'selected' : ''}>${t(`status.${status}`)}</option>`).join('')}</select></label>
            <label>${tr('priority')}<input type="number" name="priority" min="0" max="100" step="1" required value="${value.priority}"></label>
            <label>${tr('deadline')}<input type="date" name="deadline" value="${attr(value.deadline || '')}"></label>
            ${canAssign ? `<label>${tr('assignee')}<select name="assigned_to">${userOptions(value.assigned_to)}</select></label>` : ''}</div>
            ${creating ? `<label>${tr('description')} (Markdown)<textarea name="description" rows="7"></textarea></label>` : ''}`;
        formDialog(creating ? tr('new') : tr('editDetails'), body, async form => {
            const data = { title: form.elements.title.value, status: form.elements.status.value,
                priority: Number(form.elements.priority.value), deadline: form.elements.deadline.value || null };
            if (canAssign) data.assigned_to = form.elements.assigned_to.value ? Number(form.elements.assigned_to.value) : null;
            if (creating) data.description = form.elements.description.value;
            else for (const key of Object.keys(data)) if (data[key] === issue[key]) delete data[key];
            return request(creating ? '/api/issues' : `/api/issues/${issue.id}`, jsonOptions(creating ? 'POST' : 'PUT', data));
        }, result => {
            if (creating) navigateIssue(result.id);
            else if (state.issueId === result.id) {
                state.issue = result;
                document.getElementById('issue-metadata-panel').innerHTML = metadataMarkup(result);
                bindMetadata(result);
                window.dispatchEvent(new CustomEvent('issue-changed', { detail: { issueId: result.id, issue: result } }));
            }
        });
    }

    async function openEditors(issueId) {
        try {
            const data = await request(`/api/issues/${issueId}/editors`);
            const userMap = new Map([...state.users, ...data.items].map(user => [user.id, user]));
            const body = `<p>${tr('editorsHelp')}</p><div class="issue-editor-choices">${[...userMap.values()].map(user => `<label><input type="checkbox" name="editor-${user.id}" value="${user.id}" ${data.user_ids.includes(user.id) ? 'checked' : ''}>${esc(userLabel(user))}</label>`).join('')}</div>`;
            formDialog(tr('editors'), body, form => {
                const user_ids = [...form.querySelectorAll('input[type=checkbox]:checked')].map(input => Number(input.value));
                return request(`/api/issues/${issueId}/editors`, jsonOptions('PUT', { user_ids, revision: data.revision }));
            });
        } catch (error) { showNotification(errorText(error), 'error'); }
    }

    window.renderIssueRoute = async function ({ issueId, updateId = null }) {
        if (state.issueId === null) state.list.scroll = window.scrollY;
        state.issueId = issueId;
        state.issue = null;
        const generation = ++state.generation;
        if (issueId === null) { buildFilters(); return loadList(generation); }
        document.getElementById('filterBar').style.display = 'none';
        window.scrollTo(0, 0);
        await loadDetail(issueId, generation);
        if (updateId !== null && current(issueId, generation) && state.issue?.id === issueId) openUpdateDialog(issueId, updateId);
    };
    window.refreshIssueDetail = issueId => state.issueId === issueId ? window.renderIssueRoute({ issueId }) : Promise.resolve();
    window.initIssues = async function () {
        try { state.users = (await request('/api/users/list')).items; }
        catch (error) { showPageError(error); return; }
        return window.renderIssueRoute(parseRoute());
    };
    window.addEventListener('update-saved', event => {
        if (state.issueId === event.detail.issueId) loadUpdates(event.detail.issueId, false);
    });
    window.addEventListener('beforeunload', event => {
        if (state.uploading.size || MarkdownEditor.drafts.size || MarkdownEditor.pendingSaves.size || [...state.dialogs].some(dialog => dialog._isDirty() || dialog._isBusy())) {
            event.preventDefault(); event.returnValue = '';
        }
    });
}());

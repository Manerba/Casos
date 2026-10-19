/** Update creation ported from Tareas 7157218, text_file_editor.js.
 * Independent Issue dialog; no file editing, subtask scope or popup protocol.
 */
let updateDialogSequence = 0;
let activeUpdateDialog = null;

function updateDialogError(error) {
    const message = error?.message || '';
    return message.startsWith('updates.') ? t(message) : (message || t('common.saveError'));
}

class UpdateDialog {
    constructor(issueId, updateId, { onSaved } = {}) {
        this.issueId = Number(issueId);
        this.updateId = updateId === null ? null : Number(updateId);
        this.onSaved = onSaved;
        this.editorId = `issue-update-editor-${++updateDialogSequence}`;
        this.previousFocus = document.activeElement;
        this.controller = new AbortController();
        this.closed = false;
        this.shell = document.createElement('dialog');
        this.shell.className = 'update-dialog';
        this.shell.setAttribute('aria-labelledby', `${this.editorId}-title`);
        this.shell.innerHTML = `
            <header class="update-dialog-header">
                <h2 class="update-dialog-title" id="${this.editorId}-title"></h2>
                <button type="button" class="control-btn" data-update-close>${t('common.close')}</button>
            </header>
            <p class="update-dialog-meta" hidden></p>
            <p class="update-dialog-status" role="alert" hidden></p>
            <div class="update-dialog-content"><div id="${this.editorId}">${t('common.loading')}</div></div>`;
        this.title = this.shell.querySelector('.update-dialog-title');
        this.title.textContent = this.updateId === null ? t('updates.add') : `${t('updates.label')} #${this.updateId}`;
        this.status = this.shell.querySelector('.update-dialog-status');
        this.closeButton = this.shell.querySelector('[data-update-close]');
        this.closeButton.addEventListener('click', () => this.close());
        this.shell.addEventListener('cancel', event => { event.preventDefault(); this.close(); });
        this.shell.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                this.close();
            }
            if (event.key === 'Tab') {
                const controls = [...this.shell.querySelectorAll('button, a[href], textarea')]
                    .filter(element => !element.disabled && element.getClientRects().length);
                const first = controls[0], last = controls.at(-1);
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        });
        this.beforeUnload = event => {
            if (this.isDirty() || this.editor?.saving) { event.preventDefault(); event.returnValue = ''; }
        };
        window.addEventListener('beforeunload', this.beforeUnload);
        document.body.appendChild(this.shell);
        this.shell.showModal();
        this.closeButton.focus();
        this.ready = this.load();
    }

    endpoint() {
        return `/api/issues/${encodeURIComponent(this.issueId)}/updates` + (this.updateId === null ? '' : `/${encodeURIComponent(this.updateId)}`);
    }

    async request(options = {}) {
        let response;
        try {
            response = await fetch(this.endpoint(), { ...options, signal: this.controller.signal });
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            throw new Error(t('updates.networkError'));
        }
        let data;
        try { data = await response.json(); }
        catch { throw new Error(t('updates.responseError')); }
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : t('common.saveError'));
        return data;
    }

    metadata(data) {
        this.title.textContent = `${t('updates.label')} #${data.id} · ${data.user_name || t('updates.unknownAuthor')}`;
        const meta = this.shell.querySelector('.update-dialog-meta');
        meta.textContent = data.created_at ? `${data.created_at} UTC` : '';
        meta.hidden = !data.created_at;
    }

    async load() {
        try {
            const creating = this.updateId === null;
            const data = creating ? { content: '', content_format: 'markdown', can_write: true } : await this.request();
            if (this.closed) return false;
            if (!creating) this.metadata(data);
            this.revision = data.revision;
            this.editor = new MarkdownEditor(this.editorId, data.content, {
                label: t('updates.label'), format: data.content_format, revision: data.revision,
                readOnly: !data.can_write, saveErrorMessage: updateDialogError,
                onSave: async (content, revision) => {
                    if (!content.trim()) throw new Error(t('updates.empty'));
                    const isNew = this.updateId === null;
                    this.closeButton.disabled = true;
                    try {
                        const result = await this.request({
                            method: isNew ? 'POST' : 'PUT',
                            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                            body: JSON.stringify(isNew ? { content } : { content, revision }),
                        });
                        this.updateId = result.id;
                        this.revision = result.revision;
                        this.metadata(result);
                        const detail = { issueId: this.issueId, updateId: this.updateId, entry: result, isNew };
                        window.dispatchEvent(new CustomEvent('update-saved', { detail }));
                        try {
                            Promise.resolve(this.onSaved?.(result)).catch(() => this.showError(t('updates.refreshError')));
                        } catch { this.showError(t('updates.refreshError')); }
                        return result;
                    } finally {
                        this.closeButton.disabled = false;
                    }
                },
            });
            this.editor.preview.addEventListener('click', event => {
                const link = event.target.closest('a[href]');
                if (link) { event.preventDefault(); window.open(link.href, '_blank', 'noopener,noreferrer'); }
            });
            if (creating) {
                this.editor.editing = true;
                this.editor.updateView();
                this.editor.input.focus();
                this.shell.querySelector('[data-md-action="cancel"]').addEventListener('click', () => {
                    if (this.updateId === null) this.close();
                });
            }
            return true;
        } catch (error) {
            if (!this.closed) {
                this.shell.querySelector('.update-dialog-content').replaceChildren();
                this.showError(updateDialogError(error));
            }
            return false;
        }
    }

    isDirty() {
        const normalize = text => text.replace(/\r\n?/g, '\n');
        return this.editor?.editing && normalize(this.editor.input.value) !== normalize(this.editor.source);
    }

    showError(message) {
        if (this.closed) return;
        this.status.textContent = message;
        this.status.hidden = false;
    }

    close() {
        if (this.closed) return true;
        if (this.editor?.saving) return false;
        if (this.isDirty() && !window.confirm(t('updates.discard'))) return false;
        this.closed = true;
        this.controller.abort();
        MarkdownEditor.drafts.delete(this.editorId);
        MarkdownEditor.draftRevisions.delete(this.editorId);
        window.removeEventListener('beforeunload', this.beforeUnload);
        this.shell.close();
        this.shell.remove();
        if (activeUpdateDialog === this) activeUpdateDialog = null;
        if (this.previousFocus?.isConnected) this.previousFocus.focus();
        return true;
    }
}

function openUpdateDialog(issueId, updateId = null, options = {}) {
    if (activeUpdateDialog && !activeUpdateDialog.close()) return activeUpdateDialog;
    activeUpdateDialog = new UpdateDialog(issueId, updateId, options);
    return activeUpdateDialog;
}

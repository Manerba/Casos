/**
 * Tareas Admin - Benutzer-Tab
 * Benutzerverwaltung mit ExpandableTable
 */

let benutzerTable = null;
let benutzerData = [];

// ========================================
// Tab Initialisierung
// ========================================

async function initBenutzerTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    // Control-Bar aufbauen
    const filterBar = document.getElementById('filterBar');
    if (filterBar) {
        filterBar.style.display = 'flex';
        filterBar.innerHTML = `
            <div class="control-bar">
                <button class="control-btn primary" onclick="openNewUserModal()">+ Neuer Benutzer</button>
                <span class="spacer"></span>
                <input type="text" class="control-search" id="userSearchInput"
                       placeholder="Suche..." oninput="applyUserSearch(this.value)">
            </div>
        `;
    }

    // Config client-seitig
    const config = {
        id: 'benutzer',
        apiEndpoint: '/api/admin/users',
        expandable: true,
        columns: [
            { label: 'Nachname', field: 'nachname', width: 0, sortable: true },
            { label: 'Vorname', field: 'vorname', width: 150, sortable: true },
            { label: 'Benutzername', field: 'username', width: 150, sortable: true },
            { label: 'E-Mail', field: 'email', width: 200, sortable: true },
            { label: 'Admin', field: 'is_admin', width: 70, sortable: true, align: 'center', renderer: 'adminBadge' },
            { label: 'Erstellt', field: 'created_at', width: 120, sortable: true },
        ],
        detailFields: [],
        defaultSort: { field: 'nachname', direction: 'asc' },
        filters: [
            {
                id: 'userSearch',
                label: 'Suche',
                type: 'input',
                field: 'username',
                wildcard: true,
                wildcardFields: ['vorname', 'nachname', 'email'],
            },
        ],
    };

    container.innerHTML = '<div id="benutzerTableContainer"></div>';

    benutzerTable = new ExpandableTable(config, 'benutzerTableContainer', {
        onRowExpanded: onUserRowExpanded,
    });

    benutzerTable.renderers['adminBadge'] = renderAdminBadge;

    if (typeof window.tables === 'undefined') window.tables = {};
    window.tables['benutzer'] = benutzerTable;

    await benutzerTable.loadData();
}

function applyUserSearch(value) {
    if (!benutzerTable) return;
    benutzerTable.setFilter('userSearch', value);
}

// ========================================
// Renderer
// ========================================

function renderAdminBadge(value) {
    if (value) {
        return '<span class="badge badge-admin">Admin</span>';
    }
    return '';
}

// ========================================
// Detail-Bereich
// ========================================

function onUserRowExpanded(rowId, detailElement) {
    if (!detailElement || !benutzerTable) return;

    const row = benutzerTable.filteredData.find(r => String(r.id) === String(rowId));
    if (!row) return;

    const html = `<div class="detail-edit" data-user-id="${row.id}">
        <div class="detail-edit-header">
            <div class="detail-edit-field">
                <label>Nachname</label>
                <input type="text" id="editNachname_${row.id}" value="${escapeAttr(row.nachname)}">
            </div>
            <div class="detail-edit-field">
                <label>Vorname</label>
                <input type="text" id="editVorname_${row.id}" value="${escapeAttr(row.vorname)}">
            </div>
            <div class="detail-edit-field">
                <label>E-Mail</label>
                <input type="email" id="editEmail_${row.id}" value="${escapeAttr(row.email)}">
            </div>
            <div class="detail-edit-field">
                <label>Admin</label>
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;">
                    <input type="checkbox" id="editAdmin_${row.id}" ${row.is_admin ? 'checked' : ''}>
                    Administrator
                </label>
            </div>
        </div>
        <div class="detail-edit-header" style="margin-top:12px">
            <div class="detail-edit-field">
                <label>Neues Passwort (leer = nicht aendern)</label>
                <input type="password" id="editPassword_${row.id}" placeholder="Neues Passwort..." autocomplete="new-password">
            </div>
        </div>
        <div class="detail-edit-actions">
            <button class="action-btn primary" onclick="saveUser(${row.id})">Speichern</button>
            <button class="action-btn danger" onclick="deleteUser(${row.id}, '${escapeAttr(row.username)}')">Loeschen</button>
        </div>
    </div>`;

    detailElement.innerHTML = html;
}

function escapeAttr(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ========================================
// User CRUD
// ========================================

async function saveUser(userId) {
    const vorname = document.getElementById(`editVorname_${userId}`)?.value || '';
    const nachname = document.getElementById(`editNachname_${userId}`)?.value || '';
    const email = document.getElementById(`editEmail_${userId}`)?.value || '';
    const is_admin = document.getElementById(`editAdmin_${userId}`)?.checked ? 1 : 0;
    const password = document.getElementById(`editPassword_${userId}`)?.value || '';

    const body = { vorname, nachname, email, is_admin };
    if (password) body.password = password;

    try {
        const resp = await fetch(`/api/admin/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Fehler beim Speichern');
        }

        showNotification('Benutzer gespeichert', 'success');
        await benutzerTable.loadData();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function deleteUser(userId, username) {
    if (!await msgbox('cancel/yes', 'warning', `Benutzer "${username}" wirklich loeschen?`)) return;

    try {
        const resp = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || 'Fehler beim Loeschen');
        }

        showNotification('Benutzer geloescht', 'success');
        await benutzerTable.loadData();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

// ========================================
// Modal: Neuer Benutzer
// ========================================

function openNewUserModal() {
    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">Neuer Benutzer</div>
            <div class="modal-body">
                <div class="modal-field">
                    <label>Benutzername *</label>
                    <input type="text" id="newUsername" placeholder="Benutzername..." autofocus autocomplete="off">
                </div>
                <div class="modal-field">
                    <label>Vorname</label>
                    <input type="text" id="newVorname" placeholder="Vorname...">
                </div>
                <div class="modal-field">
                    <label>Nachname</label>
                    <input type="text" id="newNachname" placeholder="Nachname...">
                </div>
                <div class="modal-field">
                    <label>E-Mail</label>
                    <input type="email" id="newEmail" placeholder="E-Mail...">
                </div>
                <div class="modal-field">
                    <label>Passwort *</label>
                    <input type="password" id="newPassword" placeholder="Passwort..." autocomplete="new-password">
                </div>
                <div class="modal-field">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
                        <input type="checkbox" id="newIsAdmin">
                        Administrator
                    </label>
                </div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Abbrechen</button>
                <button class="action-btn primary" id="createUserBtn">Erstellen</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    const escHandler = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);

    document.getElementById('newUsername').focus();

    document.getElementById('createUserBtn').addEventListener('click', async () => {
        const username = document.getElementById('newUsername').value.trim();
        const password = document.getElementById('newPassword').value;
        const vorname = document.getElementById('newVorname').value.trim();
        const nachname = document.getElementById('newNachname').value.trim();
        const email = document.getElementById('newEmail').value.trim();
        const is_admin = document.getElementById('newIsAdmin').checked ? 1 : 0;

        if (!username) {
            showNotification('Benutzername ist Pflichtfeld', 'error');
            return;
        }
        if (!password || password.length < 4) {
            showNotification('Passwort muss mindestens 4 Zeichen haben', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, vorname, nachname, email, is_admin }),
            });

            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                throw new Error(data.detail || 'Fehler beim Erstellen');
            }

            overlay.remove();
            showNotification('Benutzer erstellt', 'success');
            await benutzerTable.loadData();
        } catch (error) {
            showNotification(error.message, 'error');
        }
    });
}

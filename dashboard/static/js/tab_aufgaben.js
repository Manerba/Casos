/**
 * Tareas - Aufgaben-Tab
 * Init, Control-Area, Renderer, Detail-Callbacks, Modal, SubTask-Verwaltung
 * Sprint B: Aufgabenzuweisung, Sichtbarkeit, Notizen
 */

let aufgabenTable = null;
let aufgabenConfig = null;
let allExpanded = false;
let cachedAreas = null;
let cachedUsers = [];

// ========================================
// Tab Initialisierung
// ========================================

async function initAufgabenTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    try {
        // Config, Areas und Users parallel laden
        const [configResp, areasResp, usersResp] = await Promise.all([
            fetch('/api/tasks/config'),
            fetch('/api/areas'),
            fetch('/api/users/list'),
        ]);
        aufgabenConfig = await configResp.json();
        const areasData = await areasResp.json();
        cachedAreas = areasData.items || [];
        const usersData = await usersResp.json();
        cachedUsers = usersData.items || [];

        // Control-Bar aufbauen
        buildControlBar();

        // Container fuer Tabelle
        container.innerHTML = '<div id="aufgabenTableContainer"></div>';

        // Tabelle erstellen
        aufgabenTable = new ExpandableTable(aufgabenConfig, 'aufgabenTableContainer', {
            onRowExpanded: onTaskRowExpanded,
        });

        // Custom Renderer registrieren
        aufgabenTable.renderers['badge'] = renderAufgabenBadge;
        aufgabenTable.renderers['priority'] = renderPriority;

        // Prioritaet-Spalte Renderer zuweisen
        const prioCol = aufgabenConfig.columns.find(c => c.field === 'priority');
        if (prioCol) prioCol.renderer = 'priority';

        window.tables['aufgaben'] = aufgabenTable;

        // Daten laden
        await aufgabenTable.loadData();
    } catch (error) {
        console.error('Aufgaben-Tab Fehler:', error);
        container.innerHTML = '<div class="table-error">Fehler beim Laden der Aufgaben</div>';
    }
}

// ========================================
// Control Bar
// ========================================

function buildControlBar() {
    const filterBar = document.getElementById('filterBar');
    if (!filterBar) return;

    filterBar.innerHTML = `
        <div class="control-bar">
            <button class="control-btn primary" onclick="openNewTaskModal()">+ Neue Aufgabe</button>
            <button class="control-btn" id="toggleAllBtn" onclick="toggleAllExpand()">Alle aufklappen</button>
            <span class="separator"></span>
            <div class="filter-group">
                <label class="filter-label">Typ:</label>
                <select class="filter-select" id="typeFilterSelect" onchange="applyControlFilter()">
                    <option value="">Alle</option>
                    <option value="aufgabe">Aufgabe</option>
                    <option value="projekt">Projekt</option>
                </select>
            </div>
            <div class="filter-group">
                <label class="filter-label">Status:</label>
                <select class="filter-select" id="statusFilterSelect" onchange="applyControlFilter()">
                    <option value="">Alle</option>
                    <option value="offen">Offen</option>
                    <option value="in_arbeit">In Arbeit</option>
                    <option value="erledigt">Erledigt</option>
                </select>
            </div>
            <span class="spacer"></span>
            <input type="text" class="control-search" id="searchFilterInput"
                   placeholder="Suche..." oninput="applySearchFilter(this.value)">
        </div>
    `;
}

function applyControlFilter() {
    if (!aufgabenTable) return;
    const typeVal = document.getElementById('typeFilterSelect')?.value || '';
    const statusVal = document.getElementById('statusFilterSelect')?.value || '';
    aufgabenTable.setFilter('typeFilter', typeVal);
    aufgabenTable.setFilter('statusFilter', statusVal);
}

function applySearchFilter(value) {
    if (!aufgabenTable) return;
    aufgabenTable.setFilter('searchFilter', value);
}

function toggleAllExpand() {
    if (!aufgabenTable) return;
    allExpanded = !allExpanded;
    aufgabenTable.toggleAllRows(allExpanded);

    const btn = document.getElementById('toggleAllBtn');
    if (btn) {
        btn.textContent = allExpanded ? 'Alle zuklappen' : 'Alle aufklappen';
        btn.classList.toggle('active', allExpanded);
    }
}

// ========================================
// Custom Renderer
// ========================================

function renderAufgabenBadge(value, col, row) {
    if (!value) return '-';
    const cssClass = value.toLowerCase().replace(/\s+/g, '_');
    const labelMap = {
        'offen': 'Offen',
        'in_arbeit': 'In Arbeit',
        'erledigt': 'Erledigt',
        'aufgabe': 'Aufgabe',
        'projekt': 'Projekt',
    };
    const label = labelMap[value] || value;
    return `<span class="badge badge-${cssClass}">${label}</span>`;
}

function renderPriority(value, col, row) {
    if (value === null || value === undefined) return '-';
    const num = parseInt(value);
    let dotClass = 'priority-medium';
    if (num <= 30) dotClass = 'priority-high';
    else if (num >= 70) dotClass = 'priority-low';
    return `<span class="priority-display"><span class="priority-dot ${dotClass}"></span>${num}</span>`;
}

// ========================================
// Berechtigungslogik
// ========================================

function getTaskPermissions(row) {
    const userId = currentUser ? currentUser.id : null;
    const isCreator = row.created_by === userId;
    const isAssignee = row.assigned_to === userId;
    const isAssigned = !!row.assigned_to;
    const isOwnTask = isCreator && !isAssigned;
    // Altdaten ohne created_by: alles editierbar
    const isLegacy = !row.created_by;

    return { isCreator, isAssignee, isAssigned, isOwnTask, isLegacy };
}

// ========================================
// Benutzer-Dropdown HTML
// ========================================

function buildUserOptions(selectedId) {
    let html = '<option value="">-- Nicht zugewiesen --</option>';
    cachedUsers.forEach(u => {
        const name = `${u.vorname} ${u.nachname}`.trim() || `User ${u.id}`;
        const sel = u.id === selectedId ? 'selected' : '';
        html += `<option value="${u.id}" ${sel}>${escapeHtml(name)}</option>`;
    });
    return html;
}

// ========================================
// Detail-Bereich: Aufgabe/Projekt aufgeklappt
// ========================================

async function onTaskRowExpanded(rowId, detailElement) {
    if (!detailElement || !aufgabenTable) return;

    const row = aufgabenTable.filteredData.find(r => String(r.id) === String(rowId));
    if (!row) return;

    const perm = getTaskPermissions(row);

    // Deadline fuer date input: DD.MM.YYYY -> YYYY-MM-DD
    const deadlineISO = convertToISO(row.deadline);

    // Felder readonly wenn Zugewiesener oder Ersteller mit Zuweisung
    const nameReadonly = perm.isAssignee || (perm.isCreator && perm.isAssigned) ? 'disabled' : '';
    const deadlineReadonly = perm.isAssignee || (perm.isCreator && perm.isAssigned) ? 'disabled' : '';
    const prioReadonly = perm.isAssignee || (perm.isCreator && perm.isAssigned) ? 'disabled' : '';
    const statusReadonly = (perm.isCreator && perm.isAssigned) ? 'disabled' : '';

    let html = `<div class="detail-edit" data-task-id="${row.id}">`;

    // Editierbare Header-Felder
    html += `<div class="detail-edit-header">
        <div class="detail-edit-field flex-grow">
            <label>Name</label>
            <input type="text" id="editName_${row.id}" value="${escapeAttr(row.name)}" ${nameReadonly} class="${nameReadonly ? 'field-readonly' : ''}">
        </div>
        <div class="detail-edit-field">
            <label>Deadline</label>
            <input type="date" id="editDeadline_${row.id}" value="${deadlineISO}" ${deadlineReadonly} class="${deadlineReadonly ? 'field-readonly' : ''}">
        </div>
        <div class="detail-edit-field">
            <label>Prioritaet</label>
            <input type="number" id="editPriority_${row.id}" value="${row.priority}" min="1" max="100" style="width:70px" ${prioReadonly} class="${prioReadonly ? 'field-readonly' : ''}">
        </div>
        <div class="detail-edit-field">
            <label>Status</label>
            <select id="editStatus_${row.id}" ${statusReadonly} class="${statusReadonly ? 'field-readonly' : ''}">
                <option value="offen" ${row.status === 'offen' ? 'selected' : ''}>Offen</option>
                <option value="in_arbeit" ${row.status === 'in_arbeit' ? 'selected' : ''}>In Arbeit</option>
                <option value="erledigt" ${row.status === 'erledigt' ? 'selected' : ''}>Erledigt</option>
            </select>
        </div>`;

    // Zuweisungs-Dropdown (nur fuer Ersteller oder Altdaten)
    if (perm.isCreator || perm.isOwnTask || perm.isLegacy) {
        html += `<div class="detail-edit-field">
            <label>Zuweisen an</label>
            <select id="editAssignedTo_${row.id}">
                ${buildUserOptions(row.assigned_to)}
            </select>
        </div>`;
    }

    html += `</div>`;

    // Beschreibung: WYSIWYG fuer Ersteller/eigene, readonly fuer Zugewiesene
    if (perm.isAssignee && !perm.isCreator) {
        // Zugewiesener: Beschreibung des Erstellers readonly
        html += `<div class="notes-section">
            <h5>Beschreibung von ${escapeHtml(row.created_by_name || 'Ersteller')}</h5>
            <div class="description-readonly">${row.description || '<em>Keine Beschreibung</em>'}</div>
        </div>`;
        // Eigener Notiz-Editor
        html += `<div class="notes-section">
            <h5>Meine Notizen</h5>
            <div id="notesEditor_${row.id}"></div>
        </div>`;
    } else if (perm.isCreator && perm.isAssigned) {
        // Ersteller mit Zuweisung: Beschreibung readonly
        html += `<div class="notes-section">
            <h5>Beschreibung</h5>
            <div class="description-readonly">${row.description || '<em>Keine Beschreibung</em>'}</div>
        </div>`;
        // Notizen des Zugewiesenen readonly (geladen via API)
        html += `<div class="notes-section" id="assigneeNotes_${row.id}">
            <h5>Notizen von ${escapeHtml(row.assigned_to_name || 'Zugewiesenem')}</h5>
            <div class="description-readonly" id="assigneeNotesContent_${row.id}"><em>Laden...</em></div>
        </div>`;
    } else {
        // Eigene Aufgabe / Altdaten: WYSIWYG-Editor
        html += `<div id="wysiwygEditor_${row.id}"></div>`;
    }

    // SubTask-Bereich fuer Projekte
    if (row.task_type === 'projekt') {
        html += `<div class="subtask-section" id="subtaskSection_${row.id}">
            <h4>Teilaufgaben</h4>
            <div id="subtaskContainer_${row.id}">
                <div class="table-loading"><div class="spinner"></div></div>
            </div>
        </div>`;
    }

    // Aktions-Buttons
    html += `<div class="detail-edit-actions">
        <button class="action-btn primary" onclick="saveTask(${row.id})">Speichern</button>`;
    if (perm.isCreator || perm.isOwnTask || perm.isLegacy) {
        html += `<button class="action-btn danger" onclick="deleteTask(${row.id})">Loeschen</button>`;
    }
    html += `</div>`;

    html += `</div>`;

    detailElement.innerHTML = html;

    // Editoren initialisieren
    if (perm.isAssignee && !perm.isCreator) {
        // Notizen-Editor fuer Zugewiesenen: Notiz laden und Editor initialisieren
        try {
            const notesResp = await fetch(`/api/tasks/${row.id}/notes`);
            const notesData = await notesResp.json();
            const myNote = (notesData.items || []).find(n => n.user_id === currentUser.id);
            new WysiwygEditor(`notesEditor_${row.id}`, myNote ? myNote.content : '');
        } catch (e) {
            new WysiwygEditor(`notesEditor_${row.id}`, '');
        }
    } else if (perm.isCreator && perm.isAssigned) {
        // Notizen des Zugewiesenen laden
        try {
            const notesResp = await fetch(`/api/tasks/${row.id}/notes`);
            const notesData = await notesResp.json();
            const assigneeNote = (notesData.items || []).find(n => n.user_id === row.assigned_to);
            const contentEl = document.getElementById(`assigneeNotesContent_${row.id}`);
            if (contentEl) {
                contentEl.innerHTML = assigneeNote && assigneeNote.content
                    ? assigneeNote.content
                    : '<em>Keine Notizen vorhanden</em>';
            }
        } catch (e) {
            const contentEl = document.getElementById(`assigneeNotesContent_${row.id}`);
            if (contentEl) contentEl.innerHTML = '<em>Fehler beim Laden</em>';
        }
    } else {
        // WYSIWYG-Editor fuer Beschreibung
        new WysiwygEditor(`wysiwygEditor_${row.id}`, row.description || '');
    }

    // SubTasks laden wenn Projekt
    if (row.task_type === 'projekt') {
        loadSubTasks(row.id);
    }
}

// ========================================
// Task CRUD
// ========================================

async function saveTask(taskId) {
    const row = aufgabenTable.filteredData.find(r => String(r.id) === String(taskId));
    const perm = row ? getTaskPermissions(row) : { isOwnTask: true, isLegacy: true, isAssignee: false, isCreator: true, isAssigned: false };

    const body = {};

    // Felder nur senden wenn nicht readonly
    if (perm.isOwnTask || perm.isLegacy) {
        body.name = document.getElementById(`editName_${taskId}`)?.value;
        body.deadline = document.getElementById(`editDeadline_${taskId}`)?.value;
        body.priority = parseInt(document.getElementById(`editPriority_${taskId}`)?.value) || 50;
        body.status = document.getElementById(`editStatus_${taskId}`)?.value;

        // WYSIWYG-Content
        const editorContainer = document.getElementById(`wysiwygEditor_${taskId}`);
        const editorContent = editorContainer?.querySelector('.wysiwyg-content');
        body.description = editorContent ? editorContent.innerHTML : '';
    } else if (perm.isAssignee) {
        // Zugewiesener darf nur Status aendern
        body.status = document.getElementById(`editStatus_${taskId}`)?.value;
    }

    // Zuweisung (nur Ersteller)
    const assignSelect = document.getElementById(`editAssignedTo_${taskId}`);
    if (assignSelect) {
        const val = assignSelect.value;
        body.assigned_to = val ? parseInt(val) : 0;
    }

    try {
        const resp = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) throw new Error('Fehler beim Speichern');

        // Notizen separat speichern (fuer Zugewiesene)
        if (perm.isAssignee && !perm.isCreator) {
            const notesContainer = document.getElementById(`notesEditor_${taskId}`);
            const notesContent = notesContainer?.querySelector('.wysiwyg-content');
            if (notesContent) {
                await fetch(`/api/tasks/${taskId}/notes`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: notesContent.innerHTML }),
                });
            }
        }

        showNotification('Aufgabe gespeichert', 'success');
        await aufgabenTable.loadData();
    } catch (error) {
        console.error('Speichern fehlgeschlagen:', error);
        showNotification('Fehler beim Speichern', 'error');
    }
}

async function deleteTask(taskId) {
    if (!await msgbox('cancel/yes', 'confirm', 'Aufgabe wirklich loeschen?')) return;

    try {
        const resp = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler beim Loeschen');

        showNotification('Aufgabe geloescht', 'success');
        await aufgabenTable.loadData();
    } catch (error) {
        console.error('Loeschen fehlgeschlagen:', error);
        showNotification('Fehler beim Loeschen', 'error');
    }
}

// ========================================
// SubTasks
// ========================================

async function loadSubTasks(taskId) {
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    if (!container) return;

    // Expanded-State merken
    const expandedIds = [];
    container.querySelectorAll('tr.subtask-row.expanded').forEach(row => {
        expandedIds.push(parseInt(row.dataset.subtaskId));
    });

    try {
        const resp = await fetch(`/api/tasks/${taskId}/subtasks`);
        const data = await resp.json();
        renderSubTasks(taskId, data.items || []);

        // Expanded-State wiederherstellen
        expandedIds.forEach(id => toggleSubTaskDetail(taskId, id));
    } catch (error) {
        console.error('SubTasks laden fehlgeschlagen:', error);
        container.innerHTML = '<div class="table-error">Fehler beim Laden</div>';
    }
}

function renderSubTasks(taskId, subtasks) {
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    if (!container) return;

    // Subtask-Daten fuer spaetere Verwendung speichern
    container._subtasksData = subtasks;

    // Parent-Task Permissions bestimmen
    const parentRow = aufgabenTable.filteredData.find(r => String(r.id) === String(taskId));

    const areasOptions = buildAreaOptions();

    let html = `<table class="subtask-table">
        <thead>
            <tr>
                <th class="pos-cell">Pos.</th>
                <th>Name</th>
                <th>Vorgaenger</th>
                <th>Bereich</th>
                <th>Von</th>
                <th>Zugewiesen an</th>
                <th>Erstellt</th>
                <th>Deadline</th>
                <th>Prioritaet</th>
                <th>Status (%)</th>
                <th></th>
            </tr>
        </thead>
        <tbody>`;

    subtasks.forEach(st => {
        const predIds = st.predecessor_ids || [];
        const predDisplay = st.predecessors_display || '';
        const statusPct = st.status_percent || 0;

        // Daten-Zeile (klickbar, reiner Text)
        html += `<tr class="subtask-row" data-subtask-id="${st.id}" onclick="toggleSubTaskDetail(${taskId}, ${st.id})">
            <td class="pos-cell"><span class="subtask-expand-icon">&#9654;</span>${st.position_number || ''}</td>
            <td>${escapeHtml(st.name)}</td>
            <td>${predDisplay ? `<span class="predecessor-display">${escapeHtml(predDisplay)}</span>` : '-'}</td>
            <td>${escapeHtml(st.area_name || '-')}</td>
            <td>${escapeHtml(st.created_by_name || '-')}</td>
            <td>${escapeHtml(st.assigned_to_name || '-')}</td>
            <td>${escapeHtml(st.created_at)}</td>
            <td>${escapeHtml(st.deadline || '-')}</td>
            <td>${renderPriority(st.priority)}</td>
            <td><span class="subtask-status-text"><span class="subtask-status-bar"><span class="subtask-status-fill" style="width:${statusPct}%"></span></span>${statusPct}%</span></td>
            <td>
                <div class="subtask-actions">
                    <button class="subtask-btn delete" onclick="event.stopPropagation(); deleteSubTask(${taskId}, ${st.id})">x</button>
                </div>
            </td>
        </tr>`;

        // Detail-Zeile (versteckt, wird bei Klick eingeblendet)
        const dlISO = convertToISO(st.deadline);
        const predOptions = subtasks
            .filter(other => other.id !== st.id)
            .map(other => `<option value="${other.id}">Pos. ${other.position_number}: ${escapeHtml(other.name)}</option>`)
            .join('');

        const predChips = predIds.map(pid => {
            const pred = subtasks.find(s => s.id === pid);
            const posLabel = pred ? pred.position_number : '?';
            return `<span class="predecessor-chip" data-pred-id="${pid}"><span>${posLabel}</span><button class="remove" onclick="event.stopPropagation(); removePredecessor(${taskId}, ${st.id}, ${pid})">&times;</button></span>`;
        }).join('');

        // SubTask Permissions
        const stPerm = getTaskPermissions(st);
        const stNameRO = stPerm.isAssignee ? 'disabled' : '';
        const stDeadlineRO = stPerm.isAssignee ? 'disabled' : '';
        const stPrioRO = stPerm.isAssignee ? 'disabled' : '';

        html += `<tr class="subtask-detail-row" data-subtask-detail-id="${st.id}">
            <td colspan="11">
                <div class="subtask-detail-content">
                    <div class="detail-edit-header">
                        <div class="detail-edit-field flex-grow">
                            <label>Name</label>
                            <input type="text" id="stEditName_${st.id}" value="${escapeAttr(st.name)}" ${stNameRO} class="${stNameRO ? 'field-readonly' : ''}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Vorgaenger</label>
                            <div class="predecessor-input">
                                <select id="predSelect_${st.id}">
                                    <option value="">--</option>
                                    ${predOptions}
                                </select>
                                <button onclick="event.stopPropagation(); addPredecessor(${taskId}, ${st.id})">+</button>
                            </div>
                        </div>
                        <div class="predecessor-chips-inline" id="predChips_${st.id}">${predChips}</div>
                        <div class="detail-edit-field">
                            <label>Bereich</label>
                            <div class="area-select-wrapper">
                                <select id="stEditArea_${st.id}">
                                    <option value="">-</option>
                                    ${areasOptions.map(a => `<option value="${a.id}" ${a.id === st.area_id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}
                                </select>
                                <button class="area-add-btn" onclick="event.stopPropagation(); addNewAreaInDetail(this, ${taskId}, ${st.id})" title="Neuer Bereich">+</button>
                            </div>
                        </div>
                        <div class="detail-edit-field">
                            <label>Deadline</label>
                            <input type="date" id="stEditDeadline_${st.id}" value="${dlISO}" ${stDeadlineRO} class="${stDeadlineRO ? 'field-readonly' : ''}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Prioritaet</label>
                            <input type="number" id="stEditPriority_${st.id}" value="${st.priority}" min="1" max="100" style="width:70px" ${stPrioRO} class="${stPrioRO ? 'field-readonly' : ''}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Status (%)</label>
                            <input type="number" id="stEditStatus_${st.id}" value="${st.status_percent}" min="0" max="100" style="width:70px">
                        </div>`;

        // Zuweisungs-Dropdown fuer SubTasks (nur Ersteller)
        if (stPerm.isCreator || stPerm.isOwnTask || stPerm.isLegacy) {
            html += `<div class="detail-edit-field">
                <label>Zuweisen an</label>
                <select id="stEditAssigned_${st.id}">
                    ${buildUserOptions(st.assigned_to)}
                </select>
            </div>`;
        }

        html += `</div>
                    <div id="stWysiwyg_${st.id}"></div>
                    <div class="detail-edit-actions">
                        <button class="action-btn primary" onclick="event.stopPropagation(); saveSubTask(${taskId}, ${st.id})">Speichern</button>
                    </div>
                </div>
            </td>
        </tr>`;
    });

    html += `</tbody></table>`;

    html += `<div class="subtask-add-row">
        <button class="control-btn" onclick="addSubTask(${taskId})">+ Teilaufgabe</button>
    </div>`;

    container.innerHTML = html;
}

function toggleSubTaskDetail(taskId, subtaskId) {
    const dataRow = document.querySelector(`tr.subtask-row[data-subtask-id="${subtaskId}"]`);
    const detailRow = document.querySelector(`tr.subtask-detail-row[data-subtask-detail-id="${subtaskId}"]`);
    if (!dataRow || !detailRow) return;

    const isExpanding = !dataRow.classList.contains('expanded');
    const rowTop = dataRow.getBoundingClientRect().top;

    dataRow.classList.toggle('expanded');
    detailRow.classList.toggle('visible');

    // Beim Zuklappen: Scroll-Position korrigieren
    if (!isExpanding) {
        const newRowTop = dataRow.getBoundingClientRect().top;
        window.scrollBy(0, newRowTop - rowTop);
    }

    // WYSIWYG-Editor beim ersten Aufklappen initialisieren
    if (isExpanding) {
        const editorContainer = document.getElementById(`stWysiwyg_${subtaskId}`);
        if (editorContainer && !editorContainer._editorInit) {
            // Subtask-Daten aus dem Container holen
            const container = document.getElementById(`subtaskContainer_${taskId}`);
            const subtasks = container?._subtasksData || [];
            const st = subtasks.find(s => s.id === subtaskId);
            new WysiwygEditor(`stWysiwyg_${subtaskId}`, st?.description || '');
            editorContainer._editorInit = true;
        }
    }
}

async function saveSubTask(taskId, subtaskId) {
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    const subtasks = container?._subtasksData || [];
    const st = subtasks.find(s => s.id === subtaskId);

    const body = {};

    body.name = document.getElementById(`stEditName_${subtaskId}`)?.value;
    body.area_id = parseInt(document.getElementById(`stEditArea_${subtaskId}`)?.value) || null;
    body.deadline = document.getElementById(`stEditDeadline_${subtaskId}`)?.value || '';
    body.priority = parseInt(document.getElementById(`stEditPriority_${subtaskId}`)?.value) || 50;
    body.status_percent = parseInt(document.getElementById(`stEditStatus_${subtaskId}`)?.value) || 0;

    // WYSIWYG-Content
    const editorContainer = document.getElementById(`stWysiwyg_${subtaskId}`);
    const editorContent = editorContainer?.querySelector('.wysiwyg-content');
    body.description = editorContent ? editorContent.innerHTML : '';

    // Aktuelle predecessor_ids sammeln
    const chipsContainer = document.getElementById(`predChips_${subtaskId}`);
    const currentChips = chipsContainer ? chipsContainer.querySelectorAll('.predecessor-chip') : [];
    body.predecessor_ids = Array.from(currentChips).map(c => parseInt(c.dataset.predId));

    // Zuweisung
    const assignSelect = document.getElementById(`stEditAssigned_${subtaskId}`);
    if (assignSelect) {
        const val = assignSelect.value;
        body.assigned_to = val ? parseInt(val) : 0;
    }

    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error('Fehler beim Speichern');

        showNotification('Teilaufgabe gespeichert', 'success');
        await loadSubTasks(taskId);
    } catch (error) {
        console.error('SubTask speichern fehlgeschlagen:', error);
        showNotification('Fehler beim Speichern', 'error');
    }
}

async function addNewAreaInDetail(btn, taskId, subtaskId) {
    const name = prompt('Neuer Bereich:');
    if (!name || !name.trim()) return;

    try {
        const resp = await fetch('/api/areas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim() }),
        });
        if (!resp.ok) throw new Error('Fehler');

        const data = await resp.json();
        cachedAreas.push({ id: data.id, name: data.name });

        // Dropdown aktualisieren und neuen Bereich auswaehlen
        const select = document.getElementById(`stEditArea_${subtaskId}`);
        if (select) {
            const option = document.createElement('option');
            option.value = data.id;
            option.textContent = data.name;
            option.selected = true;
            select.appendChild(option);
        }

        showNotification(`Bereich "${data.name}" erstellt`, 'success');
    } catch (error) {
        showNotification('Bereich existiert bereits oder Fehler', 'error');
    }
}

function buildAreaOptions() {
    return cachedAreas || [];
}

async function updateSubTask(subtaskId, field, value) {
    try {
        const body = {};
        body[field] = value;
        const resp = await fetch(`/api/subtasks/${subtaskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error('Fehler');
    } catch (error) {
        console.error('SubTask-Update fehlgeschlagen:', error);
        showNotification('Fehler beim Aktualisieren', 'error');
    }
}

async function addSubTask(taskId) {
    try {
        const resp = await fetch(`/api/tasks/${taskId}/subtasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'Neue Teilaufgabe' }),
        });
        if (!resp.ok) throw new Error('Fehler');

        await loadSubTasks(taskId);
    } catch (error) {
        console.error('SubTask anlegen fehlgeschlagen:', error);
        showNotification('Fehler beim Anlegen', 'error');
    }
}

async function deleteSubTask(taskId, subtaskId) {
    if (!await msgbox('cancel/yes', 'confirm', 'Teilaufgabe wirklich loeschen?')) return;

    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler');

        await loadSubTasks(taskId);
    } catch (error) {
        console.error('SubTask loeschen fehlgeschlagen:', error);
        showNotification('Fehler beim Loeschen', 'error');
    }
}

// ========================================
// Vorgaenger (Predecessors)
// ========================================

async function addPredecessor(taskId, subtaskId) {
    const select = document.getElementById(`predSelect_${subtaskId}`);
    if (!select || !select.value) return;

    const predId = parseInt(select.value);

    // Aktuelle Chips lesen um Duplikate zu vermeiden
    const chipsContainer = document.getElementById(`predChips_${subtaskId}`);
    if (chipsContainer && chipsContainer.querySelector(`[data-pred-id="${predId}"]`)) {
        showNotification('Vorgaenger bereits vorhanden', 'error');
        return;
    }

    // Aktuelle predecessor_ids sammeln
    const currentChips = chipsContainer ? chipsContainer.querySelectorAll('.predecessor-chip') : [];
    const predIds = Array.from(currentChips).map(c => parseInt(c.dataset.predId));
    predIds.push(predId);

    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ predecessor_ids: predIds }),
        });
        if (!resp.ok) throw new Error('Fehler');

        // Tabelle neu laden
        await loadSubTasks(taskId);
    } catch (error) {
        console.error('Vorgaenger hinzufuegen fehlgeschlagen:', error);
        showNotification('Fehler beim Hinzufuegen', 'error');
    }
}

async function removePredecessor(taskId, subtaskId, predIdToRemove) {
    if (!await msgbox('cancel/yes', 'confirm', 'Vorgaenger wirklich entfernen?')) return;

    // Aktuelle predecessor_ids sammeln und die zu entfernende rausfiltern
    const chipsContainer = document.getElementById(`predChips_${subtaskId}`);
    const currentChips = chipsContainer ? chipsContainer.querySelectorAll('.predecessor-chip') : [];
    const predIds = Array.from(currentChips)
        .map(c => parseInt(c.dataset.predId))
        .filter(id => id !== predIdToRemove);

    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ predecessor_ids: predIds }),
        });
        if (!resp.ok) throw new Error('Fehler');

        // Tabelle neu laden
        await loadSubTasks(taskId);
    } catch (error) {
        console.error('Vorgaenger entfernen fehlgeschlagen:', error);
        showNotification('Fehler beim Entfernen', 'error');
    }
}

async function addNewArea(btn, subtaskId) {
    const name = prompt('Neuer Bereich:');
    if (!name || !name.trim()) return;

    try {
        const resp = await fetch('/api/areas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim() }),
        });
        if (!resp.ok) throw new Error('Fehler');

        const data = await resp.json();
        cachedAreas.push({ id: data.id, name: data.name });

        // Dropdown aktualisieren
        const select = btn.previousElementSibling;
        if (select) {
            const option = document.createElement('option');
            option.value = data.id;
            option.textContent = data.name;
            option.selected = true;
            select.appendChild(option);

            // SubTask mit neuem Bereich aktualisieren
            if (subtaskId) {
                await updateSubTask(subtaskId, 'area_id', data.id);
            }
        }

        showNotification(`Bereich "${data.name}" erstellt`, 'success');
    } catch (error) {
        showNotification('Bereich existiert bereits oder Fehler', 'error');
    }
}

// ========================================
// Modal: Neue Aufgabe
// ========================================

function openNewTaskModal() {
    // Bestehende Modals entfernen
    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">Neue Aufgabe</div>
            <div class="modal-body">
                <div class="modal-field">
                    <label>Name *</label>
                    <input type="text" id="newTaskName" placeholder="Aufgabenname..." autofocus>
                </div>
                <div class="modal-field">
                    <label>Typ</label>
                    <select id="newTaskType">
                        <option value="aufgabe">Aufgabe</option>
                        <option value="projekt">Projekt</option>
                    </select>
                </div>
                <div class="modal-field">
                    <label>Deadline</label>
                    <input type="date" id="newTaskDeadline">
                </div>
                <div class="modal-field">
                    <label>Prioritaet (1-100)</label>
                    <input type="number" id="newTaskPriority" value="50" min="1" max="100">
                </div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Abbrechen</button>
                <button class="action-btn primary" onclick="createNewTask()">Erstellen</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // ESC schliesst Modal
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);

    // Enter im Name-Feld erstellt Aufgabe
    const nameInput = document.getElementById('newTaskName');
    if (nameInput) {
        nameInput.focus();
        nameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') createNewTask();
        });
    }
}

async function createNewTask() {
    const name = document.getElementById('newTaskName')?.value?.trim();
    if (!name) {
        showNotification('Name ist ein Pflichtfeld', 'error');
        return;
    }

    const task_type = document.getElementById('newTaskType')?.value || 'aufgabe';
    const deadline = document.getElementById('newTaskDeadline')?.value || '';
    const priority = parseInt(document.getElementById('newTaskPriority')?.value) || 50;

    try {
        const resp = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, task_type, deadline, priority }),
        });

        if (!resp.ok) throw new Error('Fehler beim Erstellen');

        // Modal schliessen
        const overlay = document.querySelector('.modal-overlay');
        if (overlay) overlay.remove();

        showNotification('Aufgabe erstellt', 'success');
        await aufgabenTable.loadData();
    } catch (error) {
        console.error('Erstellen fehlgeschlagen:', error);
        showNotification('Fehler beim Erstellen', 'error');
    }
}

// ========================================
// Hilfsfunktionen
// ========================================

function convertToISO(dateStr) {
    if (!dateStr) return '';
    // DD.MM.YYYY -> YYYY-MM-DD
    const parts = dateStr.split('.');
    if (parts.length === 3) {
        return `${parts[2]}-${parts[1]}-${parts[0]}`;
    }
    return dateStr;
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

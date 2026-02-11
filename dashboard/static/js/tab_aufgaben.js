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
let ncConfigured = false;
let ncDirectories = [];

// Auto-Save: Debounce-Timer pro Feld
const _autoSaveTimers = {};
function autoSaveDebounced(key, fn, delay = 1500) {
    clearTimeout(_autoSaveTimers[key]);
    _autoSaveTimers[key] = setTimeout(fn, delay);
}

// ========================================
// Tab Initialisierung
// ========================================

async function initAufgabenTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    try {
        // Config, Areas, Users und Nextcloud-Status parallel laden
        const [configResp, areasResp, usersResp, ncStatusResp] = await Promise.all([
            fetch('/api/tasks/config'),
            fetch('/api/areas'),
            fetch('/api/users/list'),
            fetch('/api/nextcloud/status').catch(() => ({ ok: false })),
        ]);
        aufgabenConfig = await configResp.json();
        const areasData = await areasResp.json();
        cachedAreas = areasData.items || [];
        const usersData = await usersResp.json();
        cachedUsers = usersData.items || [];

        // Nextcloud-Status
        if (ncStatusResp.ok) {
            const ncData = await ncStatusResp.json();
            ncConfigured = ncData.configured || false;
        } else {
            ncConfigured = false;
        }

        // Control-Bar aufbauen
        buildControlBar();

        // Container fuer Tabelle
        container.innerHTML = '<div id="aufgabenTableContainer"></div>';

        // Tabelle erstellen
        aufgabenTable = new ExpandableTable(aufgabenConfig, 'aufgabenTableContainer', {
            onRowExpanded: onTaskRowExpanded,
            onDataLoaded: () => buildCategoryButtons(),
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
// Category Filter Buttons
// ========================================

const _categoryLabels = {
    'team': 'Team',
    'zugewiesene': 'Zugewiesen',
    'vergebene': 'Vergeben',
    'eigene': 'Eigene',
};

function buildCategoryButtons() {
    if (!aufgabenTable) return;

    // Vorhandene Kategorien zaehlen
    const counts = {};
    (aufgabenTable.data || []).forEach(item => {
        const cat = item._category;
        if (cat) counts[cat] = (counts[cat] || 0) + 1;
    });

    // Container finden oder erstellen
    let container = document.getElementById('categoryFilterGroup');
    if (!container) {
        const controlBar = document.querySelector('.control-bar');
        if (!controlBar) return;
        // Nach dem Separator einfuegen
        const separator = controlBar.querySelector('.separator');
        if (!separator) return;
        container = document.createElement('div');
        container.id = 'categoryFilterGroup';
        container.className = 'category-filter-group';
        separator.after(container);
    }

    // Aktive Filter merken
    const activeSet = aufgabenTable.activeFilters['_category'] || new Set();

    // Buttons nur fuer vorhandene Kategorien erzeugen (feste Reihenfolge)
    const order = ['team', 'zugewiesene', 'vergebene', 'eigene'];
    let html = '';
    order.forEach(cat => {
        if (!counts[cat]) return;
        const isActive = activeSet.has(cat);
        const label = _categoryLabels[cat] || cat;
        html += `<button class="control-btn category-btn${isActive ? ' active' : ''}" data-category="${cat}" onclick="toggleCategoryFilter('${cat}')">${label} (${counts[cat]})</button>`;
    });

    container.innerHTML = html;

    // Ausblenden wenn nur eine Kategorie (kein Filtern noetig)
    container.style.display = Object.keys(counts).length <= 1 ? 'none' : '';
}

function toggleCategoryFilter(category) {
    if (!aufgabenTable) return;

    // activeFilters initialisieren falls noetig
    if (!aufgabenTable.activeFilters['_category']) {
        aufgabenTable.activeFilters['_category'] = new Set();
    }

    aufgabenTable.toggleButtonFilter('_category', category);

    // Button-Styling aktualisieren
    const container = document.getElementById('categoryFilterGroup');
    if (container) {
        const activeSet = aufgabenTable.activeFilters['_category'];
        container.querySelectorAll('.category-btn').forEach(btn => {
            const cat = btn.dataset.category;
            btn.classList.toggle('active', activeSet.has(cat));
        });
    }
}

// ========================================
// Custom Renderer
// ========================================

function renderAufgabenBadge(value, col, row) {
    if (!value) return '-';

    // Projekte: Teilaufgaben-Fortschritt anzeigen
    if (col.field === 'status' && row.task_type === 'projekt' && row.subtask_total > 0) {
        const done = row.subtask_done;
        const total = row.subtask_total;
        const cssClass = done === total ? 'erledigt' : done > 0 ? 'in_arbeit' : 'offen';
        return `<span class="badge badge-${cssClass}">${done}/${total}</span>`;
    }

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
    const isTeamMember = !!row.is_team_member;

    return { isCreator, isAssignee, isAssigned, isOwnTask, isLegacy, isTeamMember };
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

    // Zugewiesene Subtask-Ansicht (negative ID = Pseudo-Task fuer zugewiesene Subtask)
    if (row._type === 'assigned_subtask' || row.id < 0) {
        return onSubtaskViewExpanded(row, detailElement);
    }

    const perm = getTaskPermissions(row);

    // Deadline fuer date input: DD.MM.YYYY -> YYYY-MM-DD
    const deadlineISO = convertToISO(row.deadline);

    // Felder readonly je nach Rolle
    const nameReadonly = perm.isAssignee || (perm.isCreator && perm.isAssigned) ? 'disabled' : '';
    const deadlineReadonly = perm.isAssignee ? 'disabled' : '';
    const prioReadonly = perm.isAssignee ? 'disabled' : '';
    const statusReadonly = perm.isAssignee ? '' : ((perm.isCreator && perm.isAssigned) ? 'disabled' : '');

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

    // Beschreibung + Dateiablage: Zwei-Spalten-Layout wenn NC-Verzeichnis zugeordnet
    const hasNcPath = !!row.nextcloud_path && ncConfigured;

    if (hasNcPath) {
        html += `<div class="project-detail-columns">`;
        html += `<div class="project-detail-left">`;
    }

    // Beschreibung: WYSIWYG fuer Ersteller/eigene, readonly fuer Zugewiesene
    if (perm.isAssignee && !perm.isCreator) {
        html += `<div class="notes-section">
            <h5>Beschreibung von ${escapeHtml(row.created_by_name || 'Ersteller')}</h5>
            <div class="description-readonly">${row.description || '<em>Keine Beschreibung</em>'}</div>
        </div>`;
        html += `<div class="notes-section">
            <h5>Meine Notizen</h5>
            <div id="notesEditor_${row.id}"></div>
        </div>`;
    } else if (perm.isCreator && perm.isAssigned) {
        html += `<div class="notes-section">
            <h5>Beschreibung</h5>
            <div class="description-readonly">${row.description || '<em>Keine Beschreibung</em>'}</div>
        </div>`;
        html += `<div class="notes-section" id="assigneeNotes_${row.id}">
            <h5>Notizen von ${escapeHtml(row.assigned_to_name || 'Zugewiesenem')}</h5>
            <div class="description-readonly" id="assigneeNotesContent_${row.id}"><em>Laden...</em></div>
        </div>`;
    } else {
        html += `<div id="wysiwygEditor_${row.id}"></div>`;
    }

    if (hasNcPath) {
        html += `</div>`; // project-detail-left
        html += `<div class="project-detail-right">
            <div id="fileBrowserContainer_${row.id}"></div>
        </div>`;
        html += `</div>`; // project-detail-columns
        html += `<div class="project-detail-resize" id="pdResize_${row.id}"></div>`;
    }

    // Dateiablage-Button fuer Aufgaben (nicht-Projekte)
    if (row.task_type !== 'projekt' && ncConfigured && (perm.isCreator || perm.isLegacy)) {
        html += `<div class="subtask-section-actions" style="margin-top:8px;display:flex;justify-content:flex-end">
            <button class="control-btn${row.nextcloud_path ? ' nc-active' : ''}" onclick="event.stopPropagation(); openNcDirDialog(${row.id}, '${escapeAttr(row.nextcloud_path || '')}')">${row.nextcloud_path ? '&#128194; ' + escapeHtml(row.nextcloud_path) : 'Dateiablage'}</button>
        </div>`;
    }

    // SubTask-Bereich fuer Projekte
    if (row.task_type === 'projekt') {
        html += `<div class="subtask-section" id="subtaskSection_${row.id}">
            <div class="subtask-section-header">
                <h4>Teilaufgaben</h4>
                <div class="subtask-section-actions">
                    <button class="control-btn" onclick="event.stopPropagation(); openNetzplan(${row.id})">Netzplan</button>
                    ${perm.isCreator ? `<button class="team-btn" onclick="event.stopPropagation(); openTeamDialog(${row.id})">Team</button>` : ''}
                    ${ncConfigured && (perm.isCreator || perm.isLegacy) ? `<button class="control-btn${row.nextcloud_path ? ' nc-active' : ''}" onclick="event.stopPropagation(); openNcDirDialog(${row.id}, '${escapeAttr(row.nextcloud_path || '')}')">${row.nextcloud_path ? '&#128194; ' + escapeHtml(row.nextcloud_path) : 'Dateiablage'}</button>` : ''}
                </div>
            </div>
            <div id="subtaskContainer_${row.id}">
                <div class="table-loading"><div class="spinner"></div></div>
            </div>
        </div>`;
    }

    // Aktions-Buttons
    if (perm.isCreator || perm.isOwnTask || perm.isLegacy) {
        html += `<div class="detail-edit-actions">
            <button class="action-btn danger" onclick="deleteTask(${row.id})">Loeschen</button>
        </div>`;
    }

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

    // Auto-Save: Metadaten-Felder bei Aenderung sofort speichern
    ['editName', 'editDeadline', 'editPriority', 'editStatus', 'editAssignedTo'].forEach(prefix => {
        const el = document.getElementById(`${prefix}_${row.id}`);
        if (el && !el.disabled) {
            el.addEventListener('change', () => saveTask(row.id, true));
        }
    });

    // Auto-Save: WYSIWYG-Editor mit Debounce
    const wysiwygContent = document.querySelector(`#wysiwygEditor_${row.id} .wysiwyg-content`);
    if (wysiwygContent) {
        wysiwygContent.addEventListener('input', () => {
            autoSaveDebounced(`task_${row.id}`, () => saveTask(row.id, true));
        });
    }

    // Auto-Save: Notizen-Editor mit Debounce
    const notesContent = document.querySelector(`#notesEditor_${row.id} .wysiwyg-content`);
    if (notesContent) {
        notesContent.addEventListener('input', () => {
            autoSaveDebounced(`taskNotes_${row.id}`, () => saveTask(row.id, true));
        });
    }

    // File Browser initialisieren wenn Verzeichnis zugeordnet
    if (row.nextcloud_path && ncConfigured) {
        const fbContainer = document.getElementById(`fileBrowserContainer_${row.id}`);
        if (fbContainer) {
            new FileBrowser(`fileBrowserContainer_${row.id}`, row.id);
        }
        initColumnResize(row.id);
    }

    // SubTasks laden wenn Projekt
    if (row.task_type === 'projekt') {
        loadSubTasks(row.id);
    }
}


/**
 * Resize-Handle fuer Zwei-Spalten-Layout (Editor + Dateiablage).
 * Zieht man den Handle nach unten/oben, aendert sich die Hoehe beider Spalten synchron.
 */
function initColumnResize(taskId) {
    const handle = document.getElementById(`pdResize_${taskId}`);
    if (!handle) return;
    const columns = handle.previousElementSibling;
    if (!columns || !columns.classList.contains('project-detail-columns')) return;

    let startY = 0;
    let startH = 0;

    function onMouseMove(e) {
        const newH = Math.max(200, startH + (e.clientY - startY));
        columns.style.height = newH + 'px';
    }
    function onMouseUp() {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
    }
    handle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startY = e.clientY;
        startH = columns.offsetHeight;
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'ns-resize';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// ========================================
// Task CRUD
// ========================================

async function saveTask(taskId, silent = false) {
    const row = aufgabenTable.filteredData.find(r => String(r.id) === String(taskId));

    // Subtask-View: an eigene Speicherfunktion weiterleiten (negative ID = Pseudo-Task)
    if (row && (row._type === 'assigned_subtask' || row.id < 0)) {
        return saveSubtaskView(row, silent);
    }

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
    } else if (perm.isCreator && perm.isAssigned) {
        // Ersteller mit Zuweisung: nur Deadline + Prioritaet
        body.deadline = document.getElementById(`editDeadline_${taskId}`)?.value;
        body.priority = parseInt(document.getElementById(`editPriority_${taskId}`)?.value) || 50;
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

        if (!silent) {
            showNotification('Aufgabe gespeichert', 'success');
            await aufgabenTable.loadData();
        }
    } catch (error) {
        console.error('Speichern fehlgeschlagen:', error);
        showNotification('Fehler beim Speichern', 'error');
    }
}

// ========================================
// Subtask-View (zugewiesene Teilaufgabe als Aufgabe)
// ========================================

async function onSubtaskViewExpanded(row, detailElement) {
    const stId = row._subtask_id || Math.abs(row.id);
    const projectId = row._project_id;
    const deadlineISO = convertToISO(row.deadline);

    let html = `<div class="detail-edit" data-task-id="${row.id}">`;

    // Info-Hinweis
    html += `<div class="subtask-view-info">Teilaufgabe aus Projekt: <strong>${escapeHtml(row._project_name)}</strong></div>`;

    // Header-Felder (alle readonly ausser Status)
    html += `<div class="detail-edit-header">
        <div class="detail-edit-field flex-grow">
            <label>Name</label>
            <input type="text" value="${escapeAttr(row.name)}" disabled class="field-readonly">
        </div>
        <div class="detail-edit-field">
            <label>Deadline</label>
            <input type="date" value="${deadlineISO}" disabled class="field-readonly">
        </div>
        <div class="detail-edit-field">
            <label>Prioritaet</label>
            <input type="number" value="${row.priority}" disabled class="field-readonly" style="width:70px">
        </div>
        <div class="detail-edit-field">
            <label>Status</label>
            <select id="stViewStatus_${stId}">
                <option value="0" ${row._status_percent === 0 ? 'selected' : ''}>Offen</option>
                <option value="50" ${row._status_percent > 0 && row._status_percent < 100 ? 'selected' : ''}>In Arbeit</option>
                <option value="100" ${row._status_percent >= 100 ? 'selected' : ''}>Erledigt</option>
            </select>
        </div>
    </div>`;

    // Beschreibung readonly
    html += `<div class="notes-section">
        <h5>Beschreibung von ${escapeHtml(row.created_by_name || 'Ersteller')}</h5>
        <div class="description-readonly">${row.description || '<em>Keine Beschreibung</em>'}</div>
    </div>`;

    // Eigene Notizen (WYSIWYG)
    html += `<div class="notes-section">
        <h5>Meine Notizen</h5>
        <div id="stViewNotes_${stId}"></div>
    </div>`;

    html += `</div>`;
    detailElement.innerHTML = html;

    // Notizen laden und Editor initialisieren
    if (projectId) {
        try {
            const notesResp = await fetch(`/api/tasks/${projectId}/subtasks/${stId}/notes`);
            const notesData = await notesResp.json();
            const myNote = (notesData.items || []).find(n => n.user_id === currentUser.id);
            new WysiwygEditor(`stViewNotes_${stId}`, myNote ? myNote.content : '');
        } catch (e) {
            new WysiwygEditor(`stViewNotes_${stId}`, '');
        }
    } else {
        new WysiwygEditor(`stViewNotes_${stId}`, '');
    }

    // Auto-Save: Status-Feld
    const stViewStatusEl = document.getElementById(`stViewStatus_${stId}`);
    if (stViewStatusEl) {
        stViewStatusEl.addEventListener('change', () => saveSubtaskView(row, true));
    }

    // Auto-Save: Notizen-Editor mit Debounce
    const stViewNotesContent = document.querySelector(`#stViewNotes_${stId} .wysiwyg-content`);
    if (stViewNotesContent) {
        stViewNotesContent.addEventListener('input', () => {
            autoSaveDebounced(`stViewNotes_${stId}`, () => saveSubtaskView(row, true));
        });
    }
}

async function saveSubtaskView(row, silent = false) {
    const stId = row._subtask_id || Math.abs(row.id);
    const projectId = row._project_id;
    const statusPercent = parseInt(document.getElementById(`stViewStatus_${stId}`)?.value) || 0;

    try {
        // 1. Status speichern
        const resp = await fetch(`/api/subtasks/${stId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status_percent: statusPercent }),
        });
        if (!resp.ok) throw new Error('Fehler beim Speichern');

        // 2. Notizen speichern (nur wenn project_id bekannt)
        if (projectId) {
            const notesContainer = document.getElementById(`stViewNotes_${stId}`);
            const notesContent = notesContainer?.querySelector('.wysiwyg-content');
            if (notesContent) {
                await fetch(`/api/tasks/${projectId}/subtasks/${stId}/notes`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: notesContent.innerHTML }),
                });
            }
        }

        if (!silent) {
            showNotification('Teilaufgabe gespeichert', 'success');
            await aufgabenTable.loadData();
        }
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
    const parentPerm = parentRow ? getTaskPermissions(parentRow) : { isCreator: false, isLegacy: true };

    const areasOptions = buildAreaOptions();
    const colCount = parentPerm.isCreator ? 12 : 11;

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
                ${parentPerm.isCreator ? '<th class="perm-icon-cell"></th>' : ''}
                <th></th>
            </tr>
        </thead>
        <tbody>`;

    subtasks.forEach(st => {
        const predIds = st.predecessor_ids || [];
        const predDisplay = st.predecessors_display || '';
        const statusPct = st.status_percent || 0;
        const stPerms = st.permissions || { can_read: true, can_edit: true, can_create: true, has_override: false };
        const canEdit = stPerms.can_edit;
        const isSubAssigned = !!st.assigned_to;
        const isSubCreator = parentPerm.isCreator || parentPerm.isLegacy;

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
            <td>${renderAufgabenBadge(statusPct >= 100 ? 'erledigt' : statusPct > 0 ? 'in_arbeit' : 'offen', {field:'status'}, st)}</td>`;

        // Berechtigungs-Icon (nur Ersteller sieht es)
        if (parentPerm.isCreator) {
            const iconClass = stPerms.has_override ? 'perm-icon-override' : 'perm-icon-default';
            const icon = stPerms.has_override ? '&#128274;' : '&#128275;';
            html += `<td class="perm-icon-cell"><button class="perm-btn ${iconClass}" onclick="event.stopPropagation(); openSubtaskPermDialog(${taskId}, ${st.id})" title="Berechtigungen">${icon}</button></td>`;
        }

        // Delete-Button (nur Ersteller/Legacy)
        html += `<td>`;
        if (parentPerm.isCreator || parentPerm.isLegacy) {
            html += `<div class="subtask-actions">
                    <button class="subtask-btn delete" onclick="event.stopPropagation(); deleteSubTask(${taskId}, ${st.id})">x</button>
                </div>`;
        }
        html += `</td></tr>`;

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

        // Differenzierte Readonly-Logik pro Feld
        const fieldRO = !canEdit ? 'disabled' : '';
        const fieldROClass = !canEdit ? 'field-readonly' : '';
        // Creator mit zugewiesener Subtask: Name readonly, Deadline/Prio editierbar, Status readonly
        const stNameRO = (!canEdit || (isSubCreator && isSubAssigned)) ? 'disabled' : '';
        const stNameROClass = stNameRO ? 'field-readonly' : '';
        const stDeadlineRO = !canEdit ? 'disabled' : '';
        const stDeadlineROClass = stDeadlineRO ? 'field-readonly' : '';
        const stPrioRO = !canEdit ? 'disabled' : '';
        const stPrioROClass = stPrioRO ? 'field-readonly' : '';
        const stStatusRO = (!canEdit || (isSubCreator && isSubAssigned)) ? 'disabled' : '';
        const stStatusROClass = stStatusRO ? 'field-readonly' : '';

        html += `<tr class="subtask-detail-row" data-subtask-detail-id="${st.id}">
            <td colspan="${colCount}">
                <div class="subtask-detail-content">
                    <div class="detail-edit-header">
                        <div class="detail-edit-field flex-grow">
                            <label>Name</label>
                            <input type="text" id="stEditName_${st.id}" value="${escapeAttr(st.name)}" ${stNameRO} class="${stNameROClass}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Vorgaenger</label>
                            <div class="predecessor-input">
                                <select id="predSelect_${st.id}" ${fieldRO} class="${fieldROClass}">
                                    <option value="">--</option>
                                    ${predOptions}
                                </select>
                                <button onclick="event.stopPropagation(); addPredecessor(${taskId}, ${st.id})" ${fieldRO}>+</button>
                            </div>
                        </div>
                        <div class="predecessor-chips-inline" id="predChips_${st.id}">${predChips}</div>
                        <div class="detail-edit-field">
                            <label>Bereich</label>
                            <div class="area-select-wrapper">
                                <select id="stEditArea_${st.id}" ${fieldRO} class="${fieldROClass}">
                                    <option value="">-</option>
                                    ${areasOptions.map(a => `<option value="${a.id}" ${a.id === st.area_id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}
                                </select>
                                ${canEdit ? `<button class="area-add-btn" onclick="event.stopPropagation(); addNewAreaInDetail(this, ${taskId}, ${st.id})" title="Neuer Bereich">+</button>` : ''}
                            </div>
                        </div>
                        <div class="detail-edit-field">
                            <label>Deadline</label>
                            <input type="date" id="stEditDeadline_${st.id}" value="${dlISO}" ${stDeadlineRO} class="${stDeadlineROClass}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Prioritaet</label>
                            <input type="number" id="stEditPriority_${st.id}" value="${st.priority}" min="1" max="100" style="width:70px" ${stPrioRO} class="${stPrioROClass}">
                        </div>
                        <div class="detail-edit-field">
                            <label>Status</label>
                            <select id="stEditStatus_${st.id}" ${stStatusRO} class="${stStatusROClass}">
                                <option value="0" ${statusPct === 0 ? 'selected' : ''}>Offen</option>
                                <option value="50" ${statusPct > 0 && statusPct < 100 ? 'selected' : ''}>In Arbeit</option>
                                <option value="100" ${statusPct >= 100 ? 'selected' : ''}>Erledigt</option>
                            </select>
                        </div>`;

        // Zuweisungs-Dropdown fuer SubTasks (nur Ersteller)
        if (parentPerm.isCreator || parentPerm.isLegacy) {
            html += `<div class="detail-edit-field">
                <label>Zuweisen an</label>
                <select id="stEditAssigned_${st.id}">
                    ${buildUserOptions(st.assigned_to)}
                </select>
            </div>`;
        }

        html += `</div>`;

        // WYSIWYG oder Readonly-Beschreibung
        if (isSubCreator && isSubAssigned) {
            // Creator mit zugewiesener Subtask: Beschreibung readonly + Zugewiesenen-Notizen
            html += `<div class="description-readonly">${st.description || '<em>Keine Beschreibung</em>'}</div>`;
            html += `<div class="notes-section" id="stAssigneeNotes_${st.id}">
                <h5>Notizen von ${escapeHtml(st.assigned_to_name || 'Zugewiesenem')}</h5>
                <div class="description-readonly" id="stAssigneeNotesContent_${st.id}"><em>Laden...</em></div>
            </div>`;
        } else if (canEdit) {
            html += `<div id="stWysiwyg_${st.id}"></div>`;
        } else {
            html += `<div class="description-readonly">${st.description || '<em>Keine Beschreibung</em>'}</div>`;
        }

        html += `</div>
            </td>
        </tr>`;
    });

    html += `</tbody></table>`;

    // "+ Teilaufgabe"-Button: nur fuer Ersteller, Legacy, oder Teammitglieder mit can_create
    const firstSt = subtasks[0];
    const canCreate = parentPerm.isCreator || parentPerm.isLegacy || (firstSt && firstSt.permissions && firstSt.permissions.can_create);
    if (canCreate || subtasks.length === 0) {
        html += `<div class="subtask-add-row">
            <button class="control-btn" onclick="addSubTask(${taskId})">+ Teilaufgabe</button>
        </div>`;
    }

    container.innerHTML = html;
}

async function toggleSubTaskDetail(taskId, subtaskId) {
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

    // Beim Aufklappen: Editoren initialisieren + Notizen laden
    if (isExpanding) {
        const editorContainer = document.getElementById(`stWysiwyg_${subtaskId}`);
        if (editorContainer && !editorContainer._editorInit) {
            const container = document.getElementById(`subtaskContainer_${taskId}`);
            const subtasks = container?._subtasksData || [];
            const st = subtasks.find(s => s.id === subtaskId);
            const stPerms = st?.permissions || { can_edit: true };
            if (stPerms.can_edit) {
                new WysiwygEditor(`stWysiwyg_${subtaskId}`, st?.description || '');
            }
            editorContainer._editorInit = true;
        }

        // Zugewiesenen-Notizen lazy laden (fuer Creator mit zugewiesener Subtask)
        const notesContent = document.getElementById(`stAssigneeNotesContent_${subtaskId}`);
        if (notesContent && !notesContent._loaded) {
            notesContent._loaded = true;
            try {
                const notesResp = await fetch(`/api/tasks/${taskId}/subtasks/${subtaskId}/notes`);
                const notesData = await notesResp.json();
                const container = document.getElementById(`subtaskContainer_${taskId}`);
                const subtasks = container?._subtasksData || [];
                const st = subtasks.find(s => s.id === subtaskId);
                const assigneeNote = (notesData.items || []).find(n => n.user_id === st?.assigned_to);
                notesContent.innerHTML = assigneeNote && assigneeNote.content
                    ? assigneeNote.content
                    : '<em>Keine Notizen vorhanden</em>';
            } catch (e) {
                notesContent.innerHTML = '<em>Fehler beim Laden</em>';
            }
        }

        // Auto-Save: Metadaten-Felder bei Aenderung sofort speichern
        const detailRow = document.querySelector(`tr.subtask-detail-row[data-subtask-detail-id="${subtaskId}"]`);
        if (detailRow && !detailRow._autoSaveInit) {
            detailRow._autoSaveInit = true;
            ['stEditName', 'stEditArea', 'stEditDeadline', 'stEditPriority', 'stEditStatus', 'stEditAssigned'].forEach(prefix => {
                const el = document.getElementById(`${prefix}_${subtaskId}`);
                if (el && !el.disabled) {
                    el.addEventListener('change', () => saveSubTask(taskId, subtaskId, true));
                }
            });

            // Auto-Save: WYSIWYG-Editor mit Debounce
            const stEditorContent = document.querySelector(`#stWysiwyg_${subtaskId} .wysiwyg-content`);
            if (stEditorContent) {
                stEditorContent.addEventListener('input', () => {
                    autoSaveDebounced(`subtask_${subtaskId}`, () => saveSubTask(taskId, subtaskId, true));
                });
            }
        }
    }
}

async function saveSubTask(taskId, subtaskId, silent = false) {
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    const subtasks = container?._subtasksData || [];
    const st = subtasks.find(s => s.id === subtaskId);

    const body = {};

    const nameInput = document.getElementById(`stEditName_${subtaskId}`);
    if (nameInput && !nameInput.disabled) body.name = nameInput.value;

    body.area_id = parseInt(document.getElementById(`stEditArea_${subtaskId}`)?.value) || null;

    const dlInput = document.getElementById(`stEditDeadline_${subtaskId}`);
    if (dlInput && !dlInput.disabled) body.deadline = dlInput.value || '';

    const prioInput = document.getElementById(`stEditPriority_${subtaskId}`);
    if (prioInput && !prioInput.disabled) body.priority = parseInt(prioInput.value) || 50;

    const statusInput = document.getElementById(`stEditStatus_${subtaskId}`);
    if (statusInput && !statusInput.disabled) body.status_percent = parseInt(statusInput.value) || 0;

    // WYSIWYG-Content nur senden wenn Editor existiert (nicht bei readonly-Beschreibung)
    const editorContainer = document.getElementById(`stWysiwyg_${subtaskId}`);
    const editorContent = editorContainer?.querySelector('.wysiwyg-content');
    if (editorContent) body.description = editorContent.innerHTML;

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

        if (!silent) {
            showNotification('Teilaufgabe gespeichert', 'success');
            await loadSubTasks(taskId);
        }
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
// Team-Dialog (Sprint C)
// ========================================

async function openTeamDialog(projectId) {
    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content modal-wide">
            <div class="modal-header">Teammitglieder</div>
            <div class="modal-body">
                <div class="team-info-text">Sie sind der Ersteller und haben vollen Zugriff.</div>
                <div class="team-add-row">
                    <select id="teamAddUserSelect">
                        <option value="">-- Benutzer auswaehlen --</option>
                    </select>
                    <button class="control-btn primary" onclick="addTeamMember(${projectId})">+ Mitglied</button>
                </div>
                <div id="teamMembersContainer">
                    <div class="table-loading"><div class="spinner"></div></div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Schliessen</button>
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

    await loadTeamMembers(projectId);
}

async function loadTeamMembers(projectId) {
    const container = document.getElementById('teamMembersContainer');
    if (!container) return;

    try {
        const resp = await fetch(`/api/tasks/${projectId}/members`);
        if (!resp.ok) throw new Error('Fehler beim Laden');
        const data = await resp.json();
        const members = data.items || [];

        // User-Dropdown aktualisieren (ohne Ersteller und bestehende Mitglieder)
        const parentRow = aufgabenTable.filteredData.find(r => String(r.id) === String(projectId));
        const creatorId = parentRow ? parentRow.created_by : null;
        const memberIds = members.map(m => m.user_id);

        const select = document.getElementById('teamAddUserSelect');
        if (select) {
            select.innerHTML = '<option value="">-- Benutzer auswaehlen --</option>';
            cachedUsers.forEach(u => {
                if (u.id === creatorId || memberIds.includes(u.id)) return;
                const name = `${u.vorname} ${u.nachname}`.trim() || `User ${u.id}`;
                select.innerHTML += `<option value="${u.id}">${escapeHtml(name)}</option>`;
            });
        }

        if (members.length === 0) {
            container.innerHTML = '<div class="team-empty">Noch keine Teammitglieder hinzugefuegt.</div>';
            return;
        }

        let html = `<table class="team-table">
            <thead>
                <tr>
                    <th>Nachname</th>
                    <th>Vorname</th>
                    <th>E-Mail</th>
                    <th style="text-align:center">Lesen</th>
                    <th style="text-align:center">Bearbeiten</th>
                    <th style="text-align:center">Erstellen</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>`;

        members.forEach(m => {
            html += `<tr data-member-uid="${m.user_id}">
                <td>${escapeHtml(m.nachname)}</td>
                <td>${escapeHtml(m.vorname)}</td>
                <td>${escapeHtml(m.email)}</td>
                <td style="text-align:center"><input type="checkbox" ${m.can_read ? 'checked' : ''} onchange="updateTeamMember(${projectId}, ${m.user_id}, this.closest('tr'))"></td>
                <td style="text-align:center"><input type="checkbox" ${m.can_edit ? 'checked' : ''} onchange="updateTeamMember(${projectId}, ${m.user_id}, this.closest('tr'))"></td>
                <td style="text-align:center"><input type="checkbox" ${m.can_create ? 'checked' : ''} onchange="updateTeamMember(${projectId}, ${m.user_id}, this.closest('tr'))"></td>
                <td><button class="team-remove-btn" onclick="removeTeamMember(${projectId}, ${m.user_id})">x</button></td>
            </tr>`;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (error) {
        console.error('Team laden fehlgeschlagen:', error);
        container.innerHTML = '<div class="table-error">Fehler beim Laden</div>';
    }
}

async function addTeamMember(projectId) {
    const select = document.getElementById('teamAddUserSelect');
    if (!select || !select.value) {
        showNotification('Bitte Benutzer auswaehlen', 'error');
        return;
    }

    try {
        const resp = await fetch(`/api/tasks/${projectId}/members`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: parseInt(select.value), can_read: true }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Fehler');
        }

        showNotification('Mitglied hinzugefuegt', 'success');
        await loadTeamMembers(projectId);
    } catch (error) {
        showNotification(error.message || 'Fehler beim Hinzufuegen', 'error');
    }
}

async function updateTeamMember(projectId, userId, row) {
    if (!row) return;
    const checkboxes = row.querySelectorAll('input[type="checkbox"]');
    const can_read = checkboxes[0]?.checked || false;
    const can_edit = checkboxes[1]?.checked || false;
    const can_create = checkboxes[2]?.checked || false;

    try {
        const resp = await fetch(`/api/tasks/${projectId}/members/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ can_read, can_edit, can_create }),
        });
        if (!resp.ok) throw new Error('Fehler');
    } catch (error) {
        showNotification('Fehler beim Aktualisieren', 'error');
    }
}

async function removeTeamMember(projectId, userId) {
    if (!await msgbox('cancel/yes', 'confirm', 'Mitglied wirklich entfernen?')) return;

    try {
        const resp = await fetch(`/api/tasks/${projectId}/members/${userId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler');

        showNotification('Mitglied entfernt', 'success');
        await loadTeamMembers(projectId);
    } catch (error) {
        showNotification('Fehler beim Entfernen', 'error');
    }
}

// ========================================
// Subtask-Berechtigungs-Dialog (Sprint C)
// ========================================

async function openSubtaskPermDialog(projectId, subtaskId) {
    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    // Subtask-Name ermitteln
    const container = document.getElementById(`subtaskContainer_${projectId}`);
    const subtasks = container?._subtasksData || [];
    const st = subtasks.find(s => s.id === subtaskId);
    const stName = st ? st.name : `Teilaufgabe #${subtaskId}`;

    overlay.innerHTML = `
        <div class="modal-content modal-wide">
            <div class="modal-header">Berechtigungen: ${escapeHtml(stName)}</div>
            <div class="modal-body">
                <div class="team-info-text">Ueberschreibungen gelten nur fuer diese Teilaufgabe. Ohne Ueberschreibung gelten die Projekt-Standardberechtigungen.</div>
                <div id="subtaskPermContainer">
                    <div class="table-loading"><div class="spinner"></div></div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Schliessen</button>
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

    // Parallel laden: Mitglieder + Permissions
    try {
        const [membersResp, permsResp] = await Promise.all([
            fetch(`/api/tasks/${projectId}/members`),
            fetch(`/api/subtasks/${subtaskId}/permissions`),
        ]);
        const membersData = await membersResp.json();
        const permsData = await permsResp.json();
        const members = membersData.items || [];
        const perms = permsData.items || [];

        const permContainer = document.getElementById('subtaskPermContainer');
        if (!permContainer) return;

        if (members.length === 0) {
            permContainer.innerHTML = '<div class="team-empty">Keine Teammitglieder vorhanden.</div>';
            return;
        }

        // Permissions als Map
        const permMap = {};
        perms.forEach(p => { permMap[p.user_id] = p; });

        let html = `<table class="team-table">
            <thead>
                <tr>
                    <th>Nachname</th>
                    <th>Vorname</th>
                    <th style="text-align:center">Lesen</th>
                    <th style="text-align:center">Bearbeiten</th>
                    <th style="text-align:center">Override</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>`;

        members.forEach(m => {
            const override = permMap[m.user_id];
            const hasOverride = !!override;
            const canRead = hasOverride ? override.can_read : m.can_read;
            const canEdit = hasOverride ? override.can_edit : m.can_edit;

            html += `<tr data-perm-uid="${m.user_id}">
                <td>${escapeHtml(m.nachname)}</td>
                <td>${escapeHtml(m.vorname)}</td>
                <td style="text-align:center"><input type="checkbox" ${canRead ? 'checked' : ''} onchange="updateSubtaskPerm(${subtaskId}, ${m.user_id}, this.closest('tr'))"></td>
                <td style="text-align:center"><input type="checkbox" ${canEdit ? 'checked' : ''} onchange="updateSubtaskPerm(${subtaskId}, ${m.user_id}, this.closest('tr'))"></td>
                <td style="text-align:center">${hasOverride ? '<span class="override-indicator"></span>' : '-'}</td>
                <td>${hasOverride ? `<button class="team-remove-btn" onclick="resetSubtaskPerm(${projectId}, ${subtaskId}, ${m.user_id})">Reset</button>` : ''}</td>
            </tr>`;
        });

        html += '</tbody></table>';
        permContainer.innerHTML = html;
    } catch (error) {
        console.error('Subtask-Berechtigungen laden fehlgeschlagen:', error);
        const permContainer = document.getElementById('subtaskPermContainer');
        if (permContainer) permContainer.innerHTML = '<div class="table-error">Fehler beim Laden</div>';
    }
}

async function updateSubtaskPerm(subtaskId, userId, row) {
    if (!row) return;
    const checkboxes = row.querySelectorAll('input[type="checkbox"]');
    const can_read = checkboxes[0]?.checked || false;
    const can_edit = checkboxes[1]?.checked || false;

    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}/permissions/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ can_read, can_edit }),
        });
        if (!resp.ok) throw new Error('Fehler');
    } catch (error) {
        showNotification('Fehler beim Aktualisieren', 'error');
    }
}

async function resetSubtaskPerm(projectId, subtaskId, userId) {
    try {
        const resp = await fetch(`/api/subtasks/${subtaskId}/permissions/${userId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Fehler');

        showNotification('Ueberschreibung entfernt', 'success');
        // Dialog neu laden
        await openSubtaskPermDialog(projectId, subtaskId);
    } catch (error) {
        showNotification('Fehler beim Entfernen', 'error');
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

// ========================================
// Netzplan (Projekt-Aufgabengraph)
// ========================================

let netzplanNetwork = null;

function getNetzplanColors() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
        nodeOffen: { background: isDark ? '#4a4a5a' : '#bdc3c7', border: isDark ? '#6a6a7a' : '#95a5a6', font: isDark ? '#e8e8e8' : '#333333' },
        nodeArbeit: { background: isDark ? '#1a5276' : '#d4e6f1', border: isDark ? '#2980b9' : '#3498db', font: isDark ? '#e8e8e8' : '#333333' },
        nodeErledigt: { background: isDark ? '#1e5631' : '#d5f5e3', border: isDark ? '#27ae60' : '#28a745', font: isDark ? '#e8e8e8' : '#333333' },
        edge: isDark ? '#4a4a6a' : '#bbb',
        highlight: { background: isDark ? '#2980b9' : '#3498db', border: isDark ? '#3498db' : '#2471a3' },
    };
}

function getNodeColor(statusPercent, colors) {
    if (statusPercent >= 100) return colors.nodeErledigt;
    if (statusPercent > 0) return colors.nodeArbeit;
    return colors.nodeOffen;
}

function openNetzplan(taskId) {
    const parentRow = aufgabenTable.filteredData.find(r => String(r.id) === String(taskId));
    const projectName = parentRow ? parentRow.name : `Projekt #${taskId}`;

    // SubTasks-Daten aus dem gespeicherten Container lesen
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    const subtasks = container?._subtasksData || [];

    if (subtasks.length === 0) {
        showNotification('Keine Teilaufgaben vorhanden', 'error');
        return;
    }

    const colors = getNetzplanColors();

    // Overlay erstellen
    const overlay = document.createElement('div');
    overlay.className = 'netzplan-overlay';
    overlay.innerHTML = `
        <div class="netzplan-header">
            <div class="netzplan-title">${escapeHtml(projectName)} - Netzplan</div>
            <div class="netzplan-legend">
                <span class="netzplan-legend-item"><span class="netzplan-legend-dot status-offen"></span> Offen</span>
                <span class="netzplan-legend-item"><span class="netzplan-legend-dot status-arbeit"></span> In Arbeit</span>
                <span class="netzplan-legend-item"><span class="netzplan-legend-dot status-erledigt"></span> Erledigt</span>
            </div>
            <button class="netzplan-close-btn" title="Schliessen">&times;</button>
        </div>
        <div class="netzplan-body">
            <div class="netzplan-graph" id="netzplanGraph"></div>
            <button class="netzplan-fit-btn" id="netzplanFitBtn">Einpassen</button>
        </div>
    `;

    document.body.appendChild(overlay);

    // Graph-Daten aufbereiten
    const nodesArr = [];
    const edgesArr = [];

    // Level-Berechnung: Knoten ohne Vorgaenger = Level 0
    const levelMap = {};
    function computeLevel(st) {
        if (levelMap[st.id] !== undefined) return levelMap[st.id];
        const predIds = st.predecessor_ids || [];
        if (predIds.length === 0) {
            levelMap[st.id] = 0;
            return 0;
        }
        let maxPredLevel = 0;
        predIds.forEach(pid => {
            const pred = subtasks.find(s => s.id === pid);
            if (pred) {
                maxPredLevel = Math.max(maxPredLevel, computeLevel(pred));
            }
        });
        levelMap[st.id] = maxPredLevel + 1;
        return levelMap[st.id];
    }
    subtasks.forEach(st => computeLevel(st));

    subtasks.forEach(st => {
        const statusPct = st.status_percent || 0;
        const nodeColor = getNodeColor(statusPct, colors);
        const posLabel = st.position_number ? `${st.position_number}: ` : '';
        const label = `${posLabel}${st.name}`;

        nodesArr.push({
            id: st.id,
            label: label,
            level: levelMap[st.id],
            color: {
                background: nodeColor.background,
                border: nodeColor.border,
                highlight: { background: colors.highlight.background, border: colors.highlight.border },
            },
            font: { color: nodeColor.font, size: 13, face: "'Segoe UI', Arial, sans-serif" },
            shape: 'box',
            margin: { top: 8, right: 12, bottom: 8, left: 12 },
            borderWidth: 2,
            borderWidthSelected: 3,
            title: `${st.name}\nStatus: ${statusPct}%${st.deadline ? '\nDeadline: ' + st.deadline : ''}${st.area_name ? '\nBereich: ' + st.area_name : ''}`,
        });

        // Kanten fuer Vorgaenger
        const predIds = st.predecessor_ids || [];
        predIds.forEach(pid => {
            edgesArr.push({
                from: pid,
                to: st.id,
                arrows: { to: { enabled: true, scaleFactor: 0.8 } },
                color: { color: colors.edge, highlight: colors.highlight.border },
                smooth: { type: 'curvedCW', roundness: 0.15 },
                width: 1.5,
            });
        });
    });

    // vis-network initialisieren
    const graphContainer = document.getElementById('netzplanGraph');
    const data = { nodes: new vis.DataSet(nodesArr), edges: new vis.DataSet(edgesArr) };

    const options = {
        layout: {
            hierarchical: {
                enabled: true,
                direction: 'LR',
                sortMethod: 'directed',
                levelSeparation: 180,
                nodeSpacing: 60,
                treeSpacing: 80,
                blockShifting: true,
                edgeMinimization: true,
            },
        },
        physics: { enabled: false },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            zoomView: true,
            dragView: true,
        },
        edges: {
            smooth: { type: 'curvedCW', roundness: 0.15 },
        },
    };

    netzplanNetwork = new vis.Network(graphContainer, data, options);

    // Fit nach Rendering
    netzplanNetwork.once('afterDrawing', () => {
        netzplanNetwork.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
    });

    // Fit-Button
    document.getElementById('netzplanFitBtn').addEventListener('click', () => {
        if (netzplanNetwork) {
            netzplanNetwork.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
        }
    });

    // Theme-Wechsel: Graph-Farben aktualisieren
    const themeHandler = () => {
        if (!netzplanNetwork) return;
        const newColors = getNetzplanColors();
        subtasks.forEach(st => {
            const statusPct = st.status_percent || 0;
            const nc = getNodeColor(statusPct, newColors);
            data.nodes.update({
                id: st.id,
                color: { background: nc.background, border: nc.border, highlight: { background: newColors.highlight.background, border: newColors.highlight.border } },
                font: { color: nc.font, size: 13, face: "'Segoe UI', Arial, sans-serif" },
            });
        });
        data.edges.forEach(edge => {
            data.edges.update({ id: edge.id, color: { color: newColors.edge, highlight: newColors.highlight.border } });
        });
    };
    document.addEventListener('themeChanged', themeHandler);

    // Schliessen-Logik (mit komplettem Cleanup)
    const closeOverlay = () => {
        document.removeEventListener('themeChanged', themeHandler);
        document.removeEventListener('keydown', escHandler);
        if (netzplanNetwork) {
            netzplanNetwork.destroy();
            netzplanNetwork = null;
        }
        overlay.remove();
    };

    const escHandler = (e) => {
        if (e.key === 'Escape') closeOverlay();
    };
    document.addEventListener('keydown', escHandler);

    overlay.querySelector('.netzplan-close-btn').addEventListener('click', closeOverlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay(); });
}

// ========================================
// Nextcloud-Integration
// ========================================

async function openNcDirDialog(taskId, currentPath) {
    if (currentPath) {
        const confirmed = await msgbox('confirm', 'warning', 'Wollen Sie die Dateiablage wirklich aendern?');
        if (!confirmed) return;
    }

    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content modal-wide">
            <div class="modal-header">Dateiablage</div>
            <div class="modal-body">
                <div class="nc-browse-breadcrumb" id="ncBrowseBc"></div>
                <div id="ncDirList">
                    <div class="table-loading"><div class="spinner"></div></div>
                </div>
            </div>
            <div class="modal-footer" id="ncDirFooter">
                ${currentPath ? `<button class="action-btn danger" onclick="saveNcPath(${taskId}, '', this.closest('.modal-overlay'))">Zuordnung entfernen</button>` : ''}
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Abbrechen</button>
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

    // Browse starten bei Root
    ncBrowseDir(taskId, '', currentPath);
}

async function ncBrowseDir(taskId, browsePath, selectedPath) {
    const listContainer = document.getElementById('ncDirList');
    const bcContainer = document.getElementById('ncBrowseBc');
    if (!listContainer) return;

    listContainer.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    // Breadcrumb aktualisieren
    if (bcContainer) {
        const parts = browsePath ? browsePath.split('/').filter(Boolean) : [];
        let bcHtml = `<span class="nc-bc-item" onclick="ncBrowseDir(${taskId}, '', '${escapeAttr(selectedPath)}')">&#127968; Wurzelverzeichnis</span>`;
        let accumulated = '';
        parts.forEach(part => {
            accumulated += (accumulated ? '/' : '') + part;
            const p = accumulated;
            bcHtml += `<span class="nc-bc-sep">/</span>`;
            bcHtml += `<span class="nc-bc-item" onclick="ncBrowseDir(${taskId}, '${escapeAttr(p)}', '${escapeAttr(selectedPath)}')">${escapeHtml(part)}</span>`;
        });
        bcContainer.innerHTML = bcHtml;
    }

    // "Diesen Ordner waehlen"-Button anzeigen wenn wir nicht in Root sind
    const footer = document.getElementById('ncDirFooter');
    if (footer && browsePath) {
        // Bestehende "waehlen"-Buttons entfernen
        footer.querySelectorAll('.nc-select-btn').forEach(b => b.remove());
        const selectBtn = document.createElement('button');
        selectBtn.className = 'action-btn primary nc-select-btn';
        selectBtn.textContent = `"${browsePath.split('/').pop()}" waehlen`;
        selectBtn.onclick = () => saveNcPath(taskId, browsePath, footer.closest('.modal-overlay'));
        footer.insertBefore(selectBtn, footer.firstChild);
    } else if (footer) {
        footer.querySelectorAll('.nc-select-btn').forEach(b => b.remove());
    }

    try {
        const resp = await fetch(`/api/nextcloud/directories?path=${encodeURIComponent(browsePath)}`);
        if (!resp.ok) throw new Error('Fehler beim Laden der Verzeichnisse');
        const data = await resp.json();
        const dirs = data.directories || [];

        if (dirs.length === 0) {
            listContainer.innerHTML = '<div class="nc-dir-empty">Keine Unterverzeichnisse vorhanden</div>';
            return;
        }

        let html = '<div class="nc-dir-grid">';
        dirs.forEach(d => {
            const isSelected = d.path === selectedPath;
            html += `<div class="nc-dir-item${isSelected ? ' nc-dir-selected' : ''}">
                <span class="nc-dir-icon" onclick="event.stopPropagation(); ncBrowseDir(${taskId}, '${escapeAttr(d.path)}', '${escapeAttr(selectedPath)}')">&#128194;</span>
                <span class="nc-dir-name" onclick="event.stopPropagation(); ncBrowseDir(${taskId}, '${escapeAttr(d.path)}', '${escapeAttr(selectedPath)}')">${escapeHtml(d.name)}</span>
                <button class="nc-dir-select-btn" onclick="event.stopPropagation(); saveNcPath(${taskId}, '${escapeAttr(d.path)}', this.closest('.modal-overlay'))">${isSelected ? '&#10003; Gewaehlt' : 'Waehlen'}</button>
            </div>`;
        });
        html += '</div>';
        listContainer.innerHTML = html;
    } catch (error) {
        listContainer.innerHTML = `<p style="color:var(--color-bearish,#e74c3c)">${escapeHtml(error.message)}</p>`;
    }
}

async function saveNcPath(taskId, value, overlayEl) {
    try {
        const resp = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nextcloud_path: value }),
        });
        if (!resp.ok) throw new Error('Fehler');
        showNotification(value ? `Dateiablage "${value}" zugeordnet` : 'Dateiablage entfernt', 'success');

        // Modal schliessen
        if (overlayEl) overlayEl.remove();

        // Tabelle neu laden damit das Detail mit/ohne File Browser aktualisiert wird
        await aufgabenTable.loadData();
    } catch (error) {
        showNotification('Fehler beim Speichern der Verzeichniszuordnung', 'error');
    }
}

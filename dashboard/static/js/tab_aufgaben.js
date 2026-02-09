/**
 * Tareas - Aufgaben-Tab
 * Init, Control-Area, Renderer, Detail-Callbacks, Modal, SubTask-Verwaltung
 */

let aufgabenTable = null;
let aufgabenConfig = null;
let allExpanded = false;
let cachedAreas = null;

// ========================================
// Tab Initialisierung
// ========================================

async function initAufgabenTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    try {
        // Config und Areas parallel laden
        const [configResp, areasResp] = await Promise.all([
            fetch('/api/tasks/config'),
            fetch('/api/areas'),
        ]);
        aufgabenConfig = await configResp.json();
        const areasData = await areasResp.json();
        cachedAreas = areasData.items || [];

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
// Detail-Bereich: Aufgabe/Projekt aufgeklappt
// ========================================

function onTaskRowExpanded(rowId, detailElement) {
    if (!detailElement || !aufgabenTable) return;

    const row = aufgabenTable.filteredData.find(r => String(r.id) === String(rowId));
    if (!row) return;

    // Deadline fuer date input: DD.MM.YYYY -> YYYY-MM-DD
    const deadlineISO = convertToISO(row.deadline);

    let html = `<div class="detail-edit" data-task-id="${row.id}">`;

    // Editierbare Header-Felder
    html += `<div class="detail-edit-header">
        <div class="detail-edit-field flex-grow">
            <label>Name</label>
            <input type="text" id="editName_${row.id}" value="${escapeAttr(row.name)}">
        </div>
        <div class="detail-edit-field">
            <label>Deadline</label>
            <input type="date" id="editDeadline_${row.id}" value="${deadlineISO}">
        </div>
        <div class="detail-edit-field">
            <label>Prioritaet</label>
            <input type="number" id="editPriority_${row.id}" value="${row.priority}" min="1" max="100" style="width:70px">
        </div>
        <div class="detail-edit-field">
            <label>Status</label>
            <select id="editStatus_${row.id}">
                <option value="offen" ${row.status === 'offen' ? 'selected' : ''}>Offen</option>
                <option value="in_arbeit" ${row.status === 'in_arbeit' ? 'selected' : ''}>In Arbeit</option>
                <option value="erledigt" ${row.status === 'erledigt' ? 'selected' : ''}>Erledigt</option>
            </select>
        </div>
    </div>`;

    // WYSIWYG-Editor Container
    html += `<div id="wysiwygEditor_${row.id}"></div>`;

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
        <button class="action-btn primary" onclick="saveTask(${row.id})">Speichern</button>
        <button class="action-btn danger" onclick="deleteTask(${row.id})">Loeschen</button>
    </div>`;

    html += `</div>`;

    detailElement.innerHTML = html;

    // WYSIWYG-Editor initialisieren
    new WysiwygEditor(`wysiwygEditor_${row.id}`, row.description || '');

    // SubTasks laden wenn Projekt
    if (row.task_type === 'projekt') {
        loadSubTasks(row.id);
    }
}

// ========================================
// Task CRUD
// ========================================

async function saveTask(taskId) {
    const name = document.getElementById(`editName_${taskId}`)?.value;
    const deadline = document.getElementById(`editDeadline_${taskId}`)?.value;
    const priority = parseInt(document.getElementById(`editPriority_${taskId}`)?.value) || 50;
    const status = document.getElementById(`editStatus_${taskId}`)?.value;

    // WYSIWYG-Content
    const editorContainer = document.getElementById(`wysiwygEditor_${taskId}`);
    const editorContent = editorContainer?.querySelector('.wysiwyg-content');
    const description = editorContent ? editorContent.innerHTML : '';

    try {
        const resp = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, deadline, priority, status, description }),
        });

        if (!resp.ok) throw new Error('Fehler beim Speichern');

        showNotification('Aufgabe gespeichert', 'success');
        await aufgabenTable.loadData();
    } catch (error) {
        console.error('Speichern fehlgeschlagen:', error);
        showNotification('Fehler beim Speichern', 'error');
    }
}

async function deleteTask(taskId) {
    if (!confirm('Aufgabe wirklich loeschen?')) return;

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

    try {
        const resp = await fetch(`/api/tasks/${taskId}/subtasks`);
        const data = await resp.json();
        renderSubTasks(taskId, data.items || []);
    } catch (error) {
        console.error('SubTasks laden fehlgeschlagen:', error);
        container.innerHTML = '<div class="table-error">Fehler beim Laden</div>';
    }
}

function renderSubTasks(taskId, subtasks) {
    const container = document.getElementById(`subtaskContainer_${taskId}`);
    if (!container) return;

    const areasOptions = buildAreaOptions();

    let html = `<table class="subtask-table">
        <thead>
            <tr>
                <th class="pos-cell">Pos.</th>
                <th>Name</th>
                <th>Vorgaenger</th>
                <th>Bereich</th>
                <th>Erstellt</th>
                <th>Deadline</th>
                <th>Prioritaet</th>
                <th>Status (%)</th>
                <th></th>
            </tr>
        </thead>
        <tbody>`;

    subtasks.forEach(st => {
        const dlISO = convertToISO(st.deadline);
        // Optionen fuer Vorgaenger-Dropdown: alle anderen SubTasks des Projekts
        const predOptions = subtasks
            .filter(other => other.id !== st.id)
            .map(other => `<option value="${other.id}">Pos. ${other.position_number}: ${escapeHtml(other.name)}</option>`)
            .join('');

        // Aktuelle Vorgaenger als Chips
        const predIds = st.predecessor_ids || [];
        const predChips = predIds.map(pid => {
            const pred = subtasks.find(s => s.id === pid);
            const posLabel = pred ? pred.position_number : '?';
            return `<span class="predecessor-chip" data-pred-id="${pid}"><span>${posLabel}</span><button class="remove" onclick="removePredecessor(${taskId}, ${st.id}, ${pid})">&times;</button></span>`;
        }).join('');

        html += `<tr data-subtask-id="${st.id}">
            <td class="pos-cell">${st.position_number || ''}</td>
            <td><input type="text" class="subtask-name-input" value="${escapeAttr(st.name)}"
                       onchange="updateSubTask(${st.id}, 'name', this.value)"></td>
            <td class="predecessor-cell">
                <div class="predecessor-input">
                    <select id="predSelect_${st.id}">
                        <option value="">--</option>
                        ${predOptions}
                    </select>
                    <button onclick="addPredecessor(${taskId}, ${st.id})">+</button>
                </div>
                <div class="predecessor-chips" id="predChips_${st.id}">${predChips}</div>
            </td>
            <td>
                <div class="area-select-wrapper">
                    <select onchange="updateSubTask(${st.id}, 'area_id', this.value)">
                        <option value="">-</option>
                        ${areasOptions.map(a => `<option value="${a.id}" ${a.id === st.area_id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}
                    </select>
                    <button class="area-add-btn" onclick="addNewArea(this, ${st.id})" title="Neuer Bereich">+</button>
                </div>
            </td>
            <td>${escapeHtml(st.created_at)}</td>
            <td><input type="date" value="${dlISO}" onchange="updateSubTask(${st.id}, 'deadline', this.value)"></td>
            <td><input type="number" value="${st.priority}" min="1" max="100" style="width:60px"
                       onchange="updateSubTask(${st.id}, 'priority', parseInt(this.value))"></td>
            <td><input type="number" value="${st.status_percent}" min="0" max="100" style="width:60px"
                       onchange="updateSubTask(${st.id}, 'status_percent', parseInt(this.value))" title="${st.status_percent}%"></td>
            <td>
                <div class="subtask-actions">
                    <button class="subtask-btn delete" onclick="deleteSubTask(${taskId}, ${st.id})">x</button>
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

/**
 * Tareas - Core Module
 * Initialisierung, Theme, Settings, Tabs, URL-Routing, Notifications
 */

// ========================================
// Globaler 401-Interceptor
// ========================================

const _origFetch = window.fetch;
window.fetch = async function(url, options = {}) {
    // CSRF-Header fuer alle mutierenden API-Requests
    if (String(url).includes('/api/') && options.method && options.method !== 'GET') {
        options.headers = { 'X-Requested-With': 'XMLHttpRequest', ...options.headers };
    }
    const resp = await _origFetch.call(this, url, options);
    if (resp.status === 401 && String(url).includes('/api/')) {
        window.location.href = '/login';
    }
    return resp;
};

// ========================================
// Globale Variablen
// ========================================

let currentTab = 'aufgaben';
let currentUser = null;

// Settings Dropdown State
let settingsDropdownOpen = false;

// DOM-Cache fuer Tab-Inhalte (DocumentFragment-basiert)
const tabDOMCache = {};

// ========================================
// Initialisierung
// ========================================

document.addEventListener('DOMContentLoaded', function() {
    initTheme();
    initEventListeners();

    // Admin-Mode Guard: Tabs nur in der Haupt-App initialisieren
    if (!document.body.dataset.adminMode) {
        loadCurrentUser();
        initTabs();
    }
});

function initEventListeners() {
    // Settings-Button
    const settingsBtn = document.getElementById('settingsBtn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSettingsDropdown();
        });
    }

    // Theme Toggle
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }

    // Restart-Button
    const restartBtn = document.getElementById('restartBtn');
    if (restartBtn) {
        restartBtn.addEventListener('click', restartDashboard);
    }

    // Logout-Button
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // Passwort-Aendern-Button
    const changePasswordBtn = document.getElementById('changePasswordBtn');
    if (changePasswordBtn) {
        changePasswordBtn.addEventListener('click', openPasswordChangeModal);
    }

    // Mail-Benachrichtigungen-Button
    const mailPrefsBtn = document.getElementById('mailPrefsBtn');
    if (mailPrefsBtn) {
        mailPrefsBtn.addEventListener('click', openMailPreferencesModal);
    }

    // Tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            navigateTo(this.dataset.tab);
        });
    });

    // Klick ausserhalb Settings-Dropdown schliesst es
    document.addEventListener('click', function(e) {
        const settingsWrapper = document.querySelector('.settings-dropdown-wrapper');
        if (settingsWrapper && settingsDropdownOpen && !settingsWrapper.contains(e.target)) {
            toggleSettingsDropdown(false);
        }
    });

    // ESC schliesst Overlays
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            if (settingsDropdownOpen) {
                toggleSettingsDropdown(false);
            }
        }
    });
}

// ========================================
// User / Auth
// ========================================

async function loadCurrentUser() {
    try {
        const resp = await _origFetch('/api/auth/me');
        if (!resp.ok) {
            window.location.href = '/login';
            return;
        }
        const data = await resp.json();
        currentUser = data.user;

        const headerUsername = document.getElementById('headerUsername');
        if (headerUsername && currentUser) {
            const displayName = currentUser.vorname
                ? `${currentUser.vorname} ${currentUser.nachname}`.trim()
                : currentUser.username;
            headerUsername.textContent = displayName;
        }
    } catch (e) {
        // Netzwerkfehler - nichts tun
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
        // Ignorieren
    }
    window.location.href = '/login';
}

function openPasswordChangeModal() {
    toggleSettingsDropdown(false);

    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">Passwort aendern</div>
            <div class="modal-body">
                <div class="modal-field">
                    <label>Altes Passwort</label>
                    <input type="password" id="pwdOld" autocomplete="current-password">
                </div>
                <div class="modal-field">
                    <label>Neues Passwort</label>
                    <input type="password" id="pwdNew" autocomplete="new-password">
                </div>
                <div class="modal-field">
                    <label>Neues Passwort bestaetigen</label>
                    <input type="password" id="pwdConfirm" autocomplete="new-password">
                </div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Abbrechen</button>
                <button class="action-btn primary" id="pwdSaveBtn">Aendern</button>
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

    document.getElementById('pwdOld').focus();

    document.getElementById('pwdSaveBtn').addEventListener('click', async () => {
        const oldPwd = document.getElementById('pwdOld').value;
        const newPwd = document.getElementById('pwdNew').value;
        const confirmPwd = document.getElementById('pwdConfirm').value;

        if (!oldPwd || !newPwd) {
            showNotification('Bitte alle Felder ausfuellen', 'error');
            return;
        }
        if (newPwd !== confirmPwd) {
            showNotification('Neue Passwoerter stimmen nicht ueberein', 'error');
            return;
        }
        if (newPwd.length < 4) {
            showNotification('Passwort muss mindestens 4 Zeichen haben', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/auth/password', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
            });

            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                throw new Error(data.detail || 'Fehler');
            }

            showNotification('Passwort geaendert', 'success');
            overlay.remove();
        } catch (error) {
            showNotification(error.message, 'error');
        }
    });
}

// ========================================
// Theme Handling
// ========================================

function initTheme() {
    const savedTheme = localStorage.getItem('dashboard-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeButton(savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('dashboard-theme', newTheme);
    updateThemeButton(newTheme);

    // Custom Event fuer Komponenten
    document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: newTheme } }));
}

function updateThemeButton(theme) {
    const themeToggle = document.getElementById('themeToggle');
    const themeStatus = document.getElementById('themeStatus');
    if (themeToggle) {
        const icon = themeToggle.querySelector('.settings-icon');
        if (icon) {
            icon.textContent = theme === 'dark' ? '\u2600\uFE0F' : '\u263E';
        }
    }
    if (themeStatus) {
        themeStatus.textContent = theme === 'dark' ? 'An' : 'Aus';
    }
}

// ========================================
// Settings Dropdown
// ========================================

function toggleSettingsDropdown(forceState = null) {
    const dropdown = document.getElementById('settingsDropdown');
    const btn = document.getElementById('settingsBtn');

    if (forceState !== null) {
        settingsDropdownOpen = forceState;
    } else {
        settingsDropdownOpen = !settingsDropdownOpen;
    }

    if (dropdown) {
        dropdown.style.display = settingsDropdownOpen ? 'block' : 'none';
    }
    if (btn) {
        btn.style.transform = settingsDropdownOpen ? 'rotate(90deg)' : '';
    }
}

async function restartDashboard() {
    if (!confirm('Dashboard wirklich neu starten?')) {
        return;
    }

    const restartBtn = document.getElementById('restartBtn');
    if (restartBtn) {
        restartBtn.innerHTML = '<span class="settings-icon">\u231B</span><span class="settings-label">Wird neugestartet...</span>';
        restartBtn.style.pointerEvents = 'none';
    }

    try {
        await fetch('/api/dashboard/restart', { method: 'POST' });
    } catch (e) {
        // Erwarteter Fehler - Verbindung bricht ab
    }

    setTimeout(() => {
        location.reload();
    }, 3000);
}

// ========================================
// URL-Routing
// ========================================

function parseRoute() {
    const path = window.location.pathname.replace(/\/+$/, '') || '/';
    const segments = path.split('/').filter(Boolean);

    if (segments.length === 0) return { tab: 'aufgaben' };

    const first = segments[0];

    const tabMap = {
        'aufgaben': 'aufgaben',
    };

    return { tab: tabMap[first] || 'aufgaben' };
}

function buildPath(tab) {
    const pathMap = {
        'aufgaben': '/aufgaben',
    };
    return pathMap[tab] || '/aufgaben';
}

function navigateTo(tab, replaceState) {
    const path = buildPath(tab);
    const state = { tab };

    if (replaceState) {
        history.replaceState(state, '', path);
    } else {
        history.pushState(state, '', path);
    }

    switchTab(tab);
}

// Browser-Zurueck/Vorwaerts
window.addEventListener('popstate', function(e) {
    const route = parseRoute();
    switchTab(route.tab);
});

// ========================================
// Tab-Wechsel
// ========================================

function initTabs() {
    const route = parseRoute();
    switchTab(route.tab);
    const path = buildPath(route.tab);
    history.replaceState({ tab: route.tab }, '', path);
}

function switchTab(tab) {
    const previousTab = currentTab;
    const isSameTab = (previousTab === tab);

    // Gleicher Tab nochmal geklickt = Cache verwerfen (Refresh)
    if (isSameTab) {
        invalidateTabCache(tab);
    } else {
        saveTabDOM(previousTab);
    }

    currentTab = tab;

    // Tab-Buttons aktualisieren
    document.querySelectorAll('.main-tabs .tab').forEach(t => {
        t.classList.remove('active');
        if (t.dataset.tab === tab) {
            t.classList.add('active');
        }
    });

    const filterBar = document.getElementById('filterBar');

    // Cache vorhanden? DOM wiederherstellen
    if (!isSameTab && restoreTabDOM(tab)) {
        return;
    }

    // Kein Cache oder gleicher Tab: Init-Funktion aufrufen
    if (tab === 'aufgaben') {
        initAufgabenTab();
        if (filterBar) filterBar.style.display = 'flex';
    }
}

// ========================================
// DOM-Caching fuer Tabs
// ========================================

function saveTabDOM(tabName) {
    const contentContainer = document.getElementById('contentContainer');
    const filterBar = document.getElementById('filterBar');
    if (!contentContainer) return;

    if (contentContainer.children.length === 0) return;

    const contentFragment = document.createDocumentFragment();
    while (contentContainer.firstChild) {
        contentFragment.appendChild(contentContainer.firstChild);
    }

    const filterFragment = document.createDocumentFragment();
    let filterBarDisplay = 'none';
    if (filterBar) {
        filterBarDisplay = filterBar.style.display || window.getComputedStyle(filterBar).display;
        while (filterBar.firstChild) {
            filterFragment.appendChild(filterBar.firstChild);
        }
    }

    tabDOMCache[tabName] = {
        content: contentFragment,
        filter: filterFragment,
        filterBarDisplay: filterBarDisplay,
        scrollY: window.scrollY,
    };
}

function restoreTabDOM(tabName) {
    const cached = tabDOMCache[tabName];
    if (!cached) return false;

    const contentContainer = document.getElementById('contentContainer');
    const filterBar = document.getElementById('filterBar');

    if (contentContainer) {
        contentContainer.innerHTML = '';
        contentContainer.appendChild(cached.content);
    }

    if (filterBar) {
        filterBar.innerHTML = '';
        filterBar.appendChild(cached.filter);
        filterBar.style.display = cached.filterBarDisplay;
    }

    const savedScrollY = cached.scrollY;
    delete tabDOMCache[tabName];

    requestAnimationFrame(() => {
        window.scrollTo(0, savedScrollY);
    });

    return true;
}

function invalidateTabCache(tabName) {
    delete tabDOMCache[tabName];
}

// ========================================
// Notifications
// ========================================

function showNotification(message, type = 'info') {
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// ========================================
// Hilfsfunktionen
// ========================================

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

/**
 * HTML-Sanitizer: Nur Tags/Attribute aus WYSIWYG-Editor-Allowlist durchlassen.
 * Unerlaubte Tags werden unwrapped (Textinhalt bleibt), Attribute entfernt.
 */
function sanitizeHtml(html) {
    if (!html) return '';
    const ALLOWED_TAGS = new Set([
        'p', 'br', 'div', 'pre', 'h1', 'h2', 'h3',
        'b', 'strong', 'i', 'em', 'u',
        'ol', 'ul', 'li',
        'font',
    ]);
    const ALLOWED_ATTRS = {'font': new Set(['size'])};

    const doc = new DOMParser().parseFromString(html, 'text/html');

    function clean(parent) {
        for (const node of Array.from(parent.childNodes)) {
            if (node.nodeType === Node.TEXT_NODE) continue;
            if (node.nodeType !== Node.ELEMENT_NODE) { node.remove(); continue; }
            clean(node);
            const tag = node.tagName.toLowerCase();
            if (!ALLOWED_TAGS.has(tag)) {
                while (node.firstChild) parent.insertBefore(node.firstChild, node);
                node.remove();
            } else {
                const allowed = ALLOWED_ATTRS[tag];
                for (const a of Array.from(node.attributes)) {
                    if (!allowed || !allowed.has(a.name)) node.removeAttribute(a.name);
                }
            }
        }
    }

    clean(doc.body);
    return doc.body.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func.apply(this, args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function formatPercent(value) {
    if (value === null || value === undefined) return '-';
    return Math.round(value) + '%';
}

// ========================================
// Mail-Benachrichtigungen Modal
// ========================================

async function openMailPreferencesModal() {
    toggleSettingsDropdown(false);

    const existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="modal-content" style="max-width:500px">
            <div class="modal-header">Mail-Benachrichtigungen</div>
            <div class="modal-body">
                <div class="table-loading"><div class="spinner"></div></div>
            </div>
            <div class="modal-footer">
                <button class="action-btn" onclick="this.closest('.modal-overlay').remove()">Abbrechen</button>
                <button class="action-btn primary" id="mailPrefsSaveBtn" disabled>Speichern</button>
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

    // Prefs laden
    try {
        const resp = await fetch('/api/user/mail/preferences');
        if (!resp.ok) throw new Error('Fehler beim Laden');
        const data = await resp.json();
        const prefs = data.preferences || [];

        const eventLabels = {
            'task_assigned': 'Aufgabe zugewiesen',
            'status_change': 'Status geaendert',
            'deadline_reached': 'Faelligkeit erreicht',
            'deadline_warning': 'Faelligkeits-Vorwarnung',
        };

        let html = '<div class="mail-prefs-list">';
        for (const pref of prefs) {
            const label = eventLabels[pref.event_type] || pref.event_type;
            const checked = pref.enabled ? 'checked' : '';

            html += `<div class="mail-pref-item">
                <label>
                    <input type="checkbox" data-event="${pref.event_type}" ${checked}>
                    ${escapeHtml(label)}
                </label>`;

            if (pref.event_type === 'deadline_warning') {
                html += `<div class="mail-pref-days">
                    <input type="number" id="mailPrefDays_${pref.event_type}" value="${pref.days_before}" min="1" max="30">
                    <span>Tage vorher</span>
                </div>`;
            }

            html += '</div>';
        }
        html += '</div>';

        const modalBody = overlay.querySelector('.modal-body');
        modalBody.innerHTML = html;

        const saveBtn = document.getElementById('mailPrefsSaveBtn');
        saveBtn.disabled = false;

        saveBtn.addEventListener('click', async () => {
            const preferences = [];
            overlay.querySelectorAll('.mail-pref-item input[type="checkbox"]').forEach(cb => {
                const eventType = cb.dataset.event;
                const enabled = cb.checked;
                const daysInput = document.getElementById(`mailPrefDays_${eventType}`);
                const days_before = daysInput ? parseInt(daysInput.value) || 2 : 2;
                preferences.push({ event_type: eventType, enabled, days_before });
            });

            try {
                const resp = await fetch('/api/user/mail/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preferences }),
                });

                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    throw new Error(data.detail || 'Fehler beim Speichern');
                }

                showNotification('Mail-Einstellungen gespeichert', 'success');
                overlay.remove();
            } catch (error) {
                showNotification(error.message, 'error');
            }
        });
    } catch (error) {
        const modalBody = overlay.querySelector('.modal-body');
        modalBody.innerHTML = '<p style="color:var(--color-bearish)">Fehler beim Laden der Einstellungen</p>';
    }
}

// ========================================
// MsgBox - Globaler Bestaetigungsdialog
// ========================================

/**
 * Zeigt einen modalen Dialog an.
 * @param {"ok"|"cancel/yes"} buttons - Button-Layout
 * @param {"alert"|"confirm"|"warning"} type - Styling-Variante
 * @param {string} message - Nachrichtentext
 * @returns {Promise<boolean>} true bei Ok/Ja, false bei Abbrechen
 */
async function msgbox(buttons, type, message) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';

        let buttonsHtml = '';
        if (buttons === 'ok') {
            buttonsHtml = `<button class="action-btn msgbox-btn-primary" data-action="confirm">Ok</button>`;
        } else {
            buttonsHtml = `
                <button class="action-btn" data-action="cancel">Abbrechen</button>
                <button class="action-btn msgbox-btn-primary" data-action="confirm">Ja</button>`;
        }

        overlay.innerHTML = `
            <div class="modal-content msgbox-dialog type-${type}">
                <div class="modal-body">
                    <p style="margin:0;font-size:14px">${escapeHtml(message)}</p>
                </div>
                <div class="modal-footer">
                    ${buttonsHtml}
                </div>
            </div>
        `;

        const close = (result) => {
            overlay.remove();
            document.removeEventListener('keydown', keyHandler);
            resolve(result);
        };

        const cancelBtn = overlay.querySelector('[data-action="cancel"]');
        const confirmBtn = overlay.querySelector('[data-action="confirm"]');

        if (cancelBtn) cancelBtn.onclick = () => close(false);
        confirmBtn.onclick = () => close(true);
        overlay.onclick = (e) => { if (e.target === overlay) close(false); };

        const keyHandler = (e) => {
            if (e.key === 'Escape') close(false);
            if (e.key === 'Enter') close(true);
        };
        document.addEventListener('keydown', keyHandler);

        document.body.appendChild(overlay);
        confirmBtn.focus();
    });
}

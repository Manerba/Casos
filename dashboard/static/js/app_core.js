/**
 * Dashboard Template - Core Module
 * Initialisierung, Theme, Settings, Tabs, URL-Routing, Notifications
 */

// ========================================
// Globale Variablen
// ========================================

let currentTab = 'dashboard';

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
    initTabs();
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

    if (segments.length === 0) return { tab: 'dashboard' };

    const first = segments[0];

    const tabMap = {
        'dashboard': 'dashboard',
    };

    return { tab: tabMap[first] || 'dashboard' };
}

function buildPath(tab) {
    const pathMap = {
        'dashboard': '/dashboard',
    };
    return pathMap[tab] || '/dashboard';
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
    if (tab === 'dashboard') {
        initDashboardTab();
        if (filterBar) filterBar.style.display = 'none';
    }
    // Hier neue Tabs registrieren:
    // else if (tab === 'example') { initExampleTab(); }
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
// Dashboard Tab (Info-Seite)
// ========================================

async function initDashboardTab() {
    const container = document.getElementById('contentContainer');
    if (!container) return;

    container.innerHTML = '<div class="table-loading"><div class="spinner"></div></div>';

    try {
        const resp = await fetch('/api/dashboard/info');
        const info = await resp.json();
        container.innerHTML = renderDashboardInfo(info);
    } catch (error) {
        console.error('Dashboard-Fehler:', error);
        container.innerHTML = '<div class="kpi-error"><span class="kpi-error-icon">\u26A0\uFE0F</span><span class="kpi-error-text">Fehler beim Laden</span></div>';
    }
}

function renderDashboardInfo(info) {
    const componentsHtml = info.components.map(comp => `
        <div class="info-component">
            <h3>${escapeHtml(comp.name)}</h3>
            <p class="info-description">${escapeHtml(comp.description)}</p>
            <ul class="info-features">
                ${comp.features.map(f => `<li>${escapeHtml(f)}</li>`).join('')}
            </ul>
        </div>
    `).join('');

    const stepsHtml = info.how_to_add_tab.steps
        .map(s => `<li>${escapeHtml(s)}</li>`).join('');

    const apiExamples = info.api_structure.examples
        .map(e => `<li><code>${escapeHtml(e)}</code></li>`).join('');

    const apiConventions = info.api_structure.conventions
        .map(c => `<li>${escapeHtml(c)}</li>`).join('');

    return `
        <div class="dashboard-info">
            <div class="info-header">
                <h2>${escapeHtml(info.title)}</h2>
                <span class="info-version">v${escapeHtml(info.version)}</span>
            </div>
            <p class="info-lead">${escapeHtml(info.description)}</p>

            <section class="info-section">
                <h2>Verfuegbare Komponenten</h2>
                <div class="info-components-grid">
                    ${componentsHtml}
                </div>
            </section>

            <section class="info-section">
                <h2>Neuen Tab hinzufuegen</h2>
                <ol class="info-steps">
                    ${stepsHtml}
                </ol>
                <p class="info-hint">${escapeHtml(info.how_to_add_tab.example)}</p>
            </section>

            <section class="info-section">
                <h2>API-Struktur</h2>
                <p>Pattern: <code>${escapeHtml(info.api_structure.pattern)}</code></p>
                <h3>Endpunkte</h3>
                <ul>${apiExamples}</ul>
                <h3>Konventionen</h3>
                <ul>${apiConventions}</ul>
            </section>
        </div>
    `;
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

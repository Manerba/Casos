/**
 * Tareas - Core Module
 * Initialisierung, Theme, Settings, Tabs, URL-Routing, Notifications
 */

// ========================================
// Globale Variablen
// ========================================

let currentTab = 'aufgaben';

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

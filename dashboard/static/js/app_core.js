/**
 * Casos - Core Module
 * Initialisierung, Theme, Einstellungen, Issue-Routing und Meldungen
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

let currentUser = null;

// Settings Dropdown State
let settingsDropdownOpen = false;

// Farbschema-Konfiguration
const COLOR_SCHEMES = [
    {
        code: 'light',
        theme: 'light',
        i18nKey: 'settings.scheme.light',
        fallbackLabel: 'Hell',
        swatches: ['#ffffff', '#172033', '#1d4ed8'],
    },
    {
        code: 'dark',
        theme: 'dark',
        i18nKey: 'settings.scheme.dark',
        fallbackLabel: 'Dunkel',
        swatches: ['#0b1220', '#020617', '#22d3ee'],
    },
    {
        code: 'graphit',
        theme: 'light',
        i18nKey: 'settings.scheme.graphit',
        fallbackLabel: 'Graphit / Cyan',
        swatches: ['#111827', '#0e7490', '#92400e'],
    },
    {
        code: 'slate',
        theme: 'light',
        i18nKey: 'settings.scheme.slate',
        fallbackLabel: 'Slate / Emerald',
        swatches: ['#1f2933', '#047857', '#be123c'],
    },
    {
        code: 'ink',
        theme: 'dark',
        i18nKey: 'settings.scheme.ink',
        fallbackLabel: 'Ink / Indigo',
        swatches: ['#111014', '#c4b5fd', '#bef264'],
    },
];


// ========================================
// Initialisierung
// ========================================

document.addEventListener('DOMContentLoaded', async function() {
    initTheme();
    initEventListeners();

    await loadCurrentUser();
    if (currentUser && window.initIssues) await window.initIssues();
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

    document.getElementById('openSettingsBtn')?.addEventListener('click', () => {
        toggleSettingsDropdown(false);
        openSettingsOverlay();
    });

    // Logout-Button
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // Language Submenu
    const langToggle = document.getElementById('langToggle');
    if (langToggle) {
        langToggle.addEventListener('click', toggleLangMenu);
        buildLangMenu();
    }

    // Der Titel fuehrt zurueck zur Issue-Liste; neue Browser-Tabs bleiben per Modifier moeglich.
    document.querySelector('.header-home')?.addEventListener('click', (e) => {
        if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigateIssue(null);
        window.scrollTo(0, 0);
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
    document.cookie = 'casos_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login';
}

function initTheme() {
    let savedScheme = normalizeColorScheme(localStorage.getItem('dashboard-color-scheme'));
    if (!localStorage.getItem('dashboard-color-scheme')) {
        // Migration vom alten separaten Dark-Mode-Schalter.
        savedScheme = localStorage.getItem('dashboard-theme') === 'dark' ? 'dark' : 'light';
    }
    applyColorScheme(savedScheme);
    initLangStatus();
}

function normalizeColorScheme(code) {
    return COLOR_SCHEMES.some(s => s.code === code) ? code : 'light';
}

function getColorScheme() {
    return normalizeColorScheme(document.documentElement.getAttribute('data-color-scheme'));
}

function getColorSchemeConfig(code = getColorScheme()) {
    const normalized = normalizeColorScheme(code);
    return COLOR_SCHEMES.find(s => s.code === normalized) || COLOR_SCHEMES[0];
}

function getColorSchemeLabel(scheme) {
    const label = t(scheme.i18nKey);
    return label === scheme.i18nKey ? scheme.fallbackLabel : label;
}

function applyColorScheme(code) {
    const cfg = getColorSchemeConfig(code);
    document.documentElement.setAttribute('data-color-scheme', cfg.code);
    document.documentElement.setAttribute('data-theme', cfg.theme);
}

function setColorScheme(code) {
    const scheme = normalizeColorScheme(code);
    const cfg = getColorSchemeConfig(scheme);
    applyColorScheme(scheme);
    localStorage.setItem('dashboard-color-scheme', scheme);

    document.dispatchEvent(new CustomEvent('colorSchemeChanged', {
        detail: { colorScheme: scheme, theme: cfg.theme },
    }));
    document.dispatchEvent(new CustomEvent('themeChanged', {
        detail: { theme: cfg.theme, colorScheme: scheme },
    }));
}

function toggleLangMenu() {
    const sub = document.getElementById('langSubMenu');
    const icon = document.getElementById('langExpandIcon');
    if (!sub) return;

    const isOpen = sub.style.display !== 'none';
    sub.style.display = isOpen ? 'none' : 'block';
    if (icon) icon.classList.toggle('open', !isOpen);
}

function buildLangMenu() {
    const sub = document.getElementById('langSubMenu');
    if (!sub) return;
    const langs = getAvailableLangs();
    const current = getLang();
    sub.innerHTML = langs.map(l => {
        const active = l.code === current ? ' active' : '';
        const check = l.code === current ? '\u2713' : '';
        return `<div class="settings-sub-item${active}" data-lang="${l.code}">
            <span class="lang-check">${check}</span>
            <span>${l.label}</span>
        </div>`;
    }).join('');
    sub.addEventListener('click', (e) => {
        const item = e.target.closest('[data-lang]');
        if (item) setLang(item.dataset.lang);
    });
}

function initLangStatus() {
    const langStatus = document.getElementById('langStatus');
    if (langStatus) {
        langStatus.textContent = getLang().toUpperCase();
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
        btn.setAttribute('aria-expanded', String(settingsDropdownOpen));
    }
}

function parseRoute() {
    const match = window.location.pathname.match(/^\/issues\/(\d+)\/?$/);
    const update = new URLSearchParams(window.location.search).get('update');
    return { issueId: match ? Number(match[1]) : null, updateId: update && /^\d+$/.test(update) ? Number(update) : null };
}

function navigateIssue(issueId, replaceState = false) {
    const path = issueId === null ? '/' : `/issues/${encodeURIComponent(issueId)}`;
    if (replaceState) history.replaceState({issueId}, '', path);
    else history.pushState({issueId}, '', path);
    window.renderIssueRoute?.(parseRoute());
}

window.addEventListener('popstate', () => window.renderIssueRoute?.(parseRoute()));

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

function escapeAttr(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * HTML-Sanitizer fuer die Markdown-Ausgabe von Beschreibungen und Updates.
 * Unerlaubte Tags werden unwrapped (Textinhalt bleibt), Attribute entfernt.
 */
function sanitizeHtml(html) {
    if (!html) return '';
    const ALLOWED_TAGS = new Set([
        'p', 'br', 'div', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'b', 'strong', 'i', 'em', 'u',
        'ol', 'ul', 'li',
        'font', 'blockquote', 'hr', 'del', 's', 'a', 'img',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
    ]);
    const ALLOWED_ATTRS = {
        font: new Set(['size']),
        a: new Set(['href', 'title']),
        img: new Set(['src', 'alt', 'title']),
        ol: new Set(['start']),
    };

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
                    if (!allowed || !allowed.has(a.name)) {
                        node.removeAttribute(a.name);
                    } else if (a.name === 'href' || a.name === 'src') {
                        try {
                            const url = new URL(a.value, window.location.href);
                            const protocols = a.name === 'href' ? ['http:', 'https:', 'mailto:'] : ['http:', 'https:'];
                            if (!protocols.includes(url.protocol)) node.removeAttribute(a.name);
                        } catch (_) {
                            node.removeAttribute(a.name);
                        }
                    }
                }
            }
        }
    }

    clean(doc.body);
    return doc.body.innerHTML;
}

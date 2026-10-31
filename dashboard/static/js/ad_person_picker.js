/* AD selection is an Issue contact, independent of Casos accounts and rights. */
(() => {
    'use strict';
    const tr = key => t(`adPeople.${key}`);
    const esc = value => escapeAttr(String(value ?? ''));
    let nextId = 0;

    class AdPersonPicker {
        static label(person) { return person ? `${person.full_name} (${person.username})` : tr('none'); }

        static markup(person) {
            const id = `ad-person-${++nextId}`;
            return `<div class="ad-person-picker" data-ad-person>
                <label for="${id}">${t('issues.affectedPerson')}</label>
                <div class="ad-person-input"><input id="${id}" name="affected_person_query" type="text"
                    autocomplete="off" spellcheck="false" maxlength="200" role="combobox" aria-autocomplete="list"
                    aria-haspopup="listbox" aria-expanded="false" aria-controls="${id}-results" aria-describedby="${id}-hint"
                    placeholder="${esc(tr('placeholder'))}" value="${person ? esc(AdPersonPicker.label(person)) : ''}">
                    <button type="button" class="issue-btn" data-ad-clear aria-label="${esc(tr('clear'))}">×</button></div>
                <input type="hidden" name="affected_person_sid" value="${esc(person?.sid || '')}">
                <div class="ad-person-dropdown" hidden><ul id="${id}-results" role="listbox" aria-label="${esc(tr('results'))}"></ul>
                    <p class="ad-person-status" role="status" aria-live="polite"></p>
                    <button type="button" class="issue-btn" data-ad-more hidden>${tr('more')}</button></div>
                <small id="${id}-hint">${tr('hint')}</small>
            </div>`;
        }

        constructor(root) {
            const input = root.querySelector('[role=combobox]');
            const sid = root.querySelector('[name=affected_person_sid]');
            const panel = root.querySelector('.ad-person-dropdown');
            const list = root.querySelector('[role=listbox]');
            const status = root.querySelector('[role=status]');
            const more = root.querySelector('[data-ad-more]');
            let sequence = 0, timer, controller, items = [], active = -1, next = null, pending = false, movingFocus = false;
            const show = value => { panel.hidden = !value; input.setAttribute('aria-expanded', String(value)); };
            const cancel = () => { clearTimeout(timer); controller?.abort(); sequence++; pending = false; };
            const focusInput = () => {
                movingFocus = true; input.focus({preventScroll: true}); movingFocus = false;
            };
            const highlight = index => {
                active = index;
                [...list.children].forEach((option, i) => option.setAttribute('aria-selected', String(i === active)));
                const option = list.children[active];
                if (option) {
                    input.setAttribute('aria-activedescendant', option.id);
                    option.scrollIntoView({block: 'nearest'});
                } else input.removeAttribute('aria-activedescendant');
            };
            const select = person => {
                if (input.disabled) return;
                cancel();
                sid.value = person?.sid || '';
                sid.dataset.selected = 'true';
                input.value = person ? AdPersonPicker.label(person) : '';
                input.setCustomValidity('');
                show(false); highlight(-1); input.focus();
            };
            const render = () => {
                list.replaceChildren();
                items.forEach((person, index) => {
                    const option = document.createElement('li');
                    option.id = `${list.id}-${index}`;
                    option.setAttribute('role', 'option');
                    option.setAttribute('aria-selected', 'false');
                    const name = document.createElement('strong'); name.textContent = person.full_name;
                    const login = document.createElement('span'); login.textContent = person.username;
                    option.append(name, login);
                    option.addEventListener('mousedown', event => event.preventDefault());
                    option.onclick = () => select(person);
                    list.appendChild(option);
                });
                highlight(-1);
            };
            const search = async (append = false) => {
                clearTimeout(timer);
                controller?.abort(); controller = new AbortController();
                const request = ++sequence, query = input.value.trim();
                if (!query || sid.value || input.disabled) return;
                show(true); status.textContent = tr('loading'); pending = true;
                let failureMessage = tr('unavailable');
                try {
                    const params = new URLSearchParams({query, offset: append ? next : 0, limit: 50});
                    const response = await fetch(`/api/ad/people?${params}`, {signal: controller.signal});
                    const data = await response.json();
                    if (request !== sequence || !root.isConnected || input.disabled) return;
                    if (!response.ok) {
                        if (typeof data.detail === 'string' && data.detail.startsWith('adPeople.')) failureMessage = t(data.detail);
                        throw new Error('Directory search failed');
                    }
                    items = append ? [...items, ...data.items] : data.items;
                    next = data.next_offset;
                    render();
                    status.textContent = items.length ? tr('choose') : tr('empty');
                    more.textContent = tr('more'); more.hidden = next === null;
                } catch (error) {
                    if (request !== sequence || !root.isConnected || error.name === 'AbortError' || input.disabled) return;
                    status.textContent = failureMessage;
                    // Retry the same page, preserving any earlier results and all drafts.
                    more.hidden = false; more.textContent = tr('retry');
                    more.onclick = () => { if (!pending) { focusInput(); search(append); } };
                    return;
                } finally { if (request === sequence) pending = false; }
                more.onclick = () => { if (!pending) { focusInput(); search(true); } };
            };
            input.addEventListener('input', () => {
                cancel(); sid.value = ''; items = []; next = null; render(); more.hidden = true;
                const query = input.value.trim();
                input.setCustomValidity(query ? tr('selectionRequired') : '');
                show(Boolean(query)); status.textContent = query ? tr('loading') : '';
                if (query) timer = setTimeout(() => search(), 250);
            });
            input.addEventListener('focus', () => { if (!movingFocus && !sid.value && input.value.trim()) search(); });
            input.addEventListener('keydown', event => {
                if (event.key === 'Escape' && !panel.hidden) {
                    event.preventDefault(); event.stopPropagation(); cancel(); show(false); highlight(-1);
                } else if (['ArrowDown', 'ArrowUp'].includes(event.key) && !panel.hidden && items.length) {
                    event.preventDefault();
                    const step = event.key === 'ArrowDown' ? 1 : -1;
                    highlight(active === -1 ? (step === 1 ? 0 : items.length - 1) : (active + step + items.length) % items.length);
                } else if (event.key === 'Enter' && !panel.hidden) {
                    event.preventDefault();
                    if (items[active]) select(items[active]);
                }
            });
            root.addEventListener('focusout', event => {
                if (!root.contains(event.relatedTarget)) { cancel(); show(false); highlight(-1); }
            });
            root.querySelector('[data-ad-clear]').onclick = () => select(null);
            root.closest('dialog').addEventListener('close', cancel, {once: true});
        }
    }
    window.AdPersonPicker = AdPersonPicker;
})();

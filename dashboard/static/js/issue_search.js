/** Search mounts into the Issue list without sharing its filters or edit state. */
(function () {
    'use strict';
    const state = {query: '', type: '', since: '', submitted: null, page: null, error: '', busy: false, sequence: 0, controller: null};
    const tr = (key, values) => t('issueSearch.' + key, values);
    let container = null;

    function mount(slot) {
        if (!slot) return;
        container = slot.id === 'issue-search-slot' ? slot : slot.querySelector('#issue-search-slot');
        if (!container) return;
        container.innerHTML = `<section class="issue-search" aria-labelledby="issue-search-title"><h3 id="issue-search-title">${escapeHtml(tr('title'))}</h3><form class="issue-search-form"><label class="issue-search-query">${escapeHtml(tr('query'))}<input type="search" id="issue-search-query" maxlength="1000" autocomplete="off" aria-describedby="issue-search-help"></label><label>${escapeHtml(tr('type'))}<select id="issue-search-type"><option value="">${escapeHtml(tr('all'))}</option><option value="issue">${escapeHtml(tr('issues'))}</option><option value="update">${escapeHtml(tr('updates'))}</option></select></label><label>${escapeHtml(tr('since'))}<input type="datetime-local" id="issue-search-since" step="1"></label><div class="issue-search-actions"><button class="issue-btn primary" type="submit" id="issue-search-submit">${escapeHtml(tr('submit'))}</button><button class="issue-btn" type="button" id="issue-search-reset">${escapeHtml(tr('reset'))}</button></div></form><p class="issue-search-help" id="issue-search-help">${escapeHtml(tr('help'))}</p><div class="issue-search-feedback" aria-live="polite" aria-atomic="true"></div><div class="issue-search-output"></div></section>`;
        container.querySelector('#issue-search-query').value = state.query;
        container.querySelector('#issue-search-type').value = state.type;
        container.querySelector('#issue-search-since').value = state.since;
        for (const [id, key] of [['issue-search-query', 'query'], ['issue-search-type', 'type'], ['issue-search-since', 'since']]) {
            container.querySelector('#' + id).addEventListener('input', event => { state[key] = event.target.value; });
            container.querySelector('#' + id).addEventListener('change', event => { state[key] = event.target.value; });
        }
        container.querySelector('form').addEventListener('submit', event => {
            event.preventDefault();
            submit({query: state.query, type: state.type, since: state.since}, 0);
        });
        container.querySelector('#issue-search-reset').onclick = () => {
            state.sequence++; state.controller?.abort();
            Object.assign(state, {query: '', type: '', since: '', page: null, submitted: null, error: '', busy: false});
            mount(container);
            container.querySelector('#issue-search-query').focus();
        };
        renderResults();
    }

    async function submit(filters, offset, focusResults = false) {
        const submittedContainer = container;
        state.controller?.abort();
        const sequence = ++state.sequence;
        state.controller = new AbortController();
        state.busy = true; state.error = '';
        state.submitted = {...filters, offset};
        renderResults();
        try {
            const params = new URLSearchParams({query: filters.query, offset: String(offset), limit: '20'});
            if (filters.type) params.set('types', filters.type);
            if (filters.since) {
                const instant = new Date(filters.since);
                if (!Number.isFinite(instant.getTime())) throw new Error(tr('invalidSince'));
                params.set('since', instant.toISOString());
            }
            const response = await fetch('/api/search?' + params, {signal: state.controller.signal});
            const data = await response.json().catch(() => { throw new Error(tr('responseError')); });
            if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : tr('requestError'));
            if (!Array.isArray(data.items) || typeof data.total !== 'number') throw new Error(tr('responseError'));
            if (sequence !== state.sequence) return;
            state.page = data;
        } catch (error) {
            if (sequence !== state.sequence || error.name === 'AbortError') return;
            state.error = error instanceof TypeError ? tr('connectionError') : error.message;
        } finally {
            if (sequence === state.sequence) {
                state.busy = false; renderResults();
                if (focusResults && container === submittedContainer && container?.isConnected) {
                    container.querySelector('.issue-search-result-link, .issue-search-feedback button')?.focus();
                }
            }
        }
    }

    function safeSnippet(element, hit) {
        // Interpret only literal mark tags. Every other token becomes a text
        // node, even if a damaged response contains markup or external URLs.
        if (typeof hit.snippet_html !== 'string') { element.textContent = hit.snippet || ''; return; }
        const decoder = document.createElement('textarea');
        let target = element;
        for (const part of hit.snippet_html.split(/(<\/?mark>)/g)) {
            if (part === '<mark>') { target = document.createElement('mark'); element.appendChild(target); }
            else if (part === '</mark>') target = element;
            else {
                decoder.innerHTML = part.replace(/</g, '&lt;').replace(/>/g, '&gt;');
                target.appendChild(document.createTextNode(decoder.value));
            }
        }
    }

    function renderResults() {
        if (!container?.isConnected) return;
        const section = container.querySelector('.issue-search');
        section.setAttribute('aria-busy', String(state.busy));
        const feedback = container.querySelector('.issue-search-feedback');
        feedback.replaceChildren();
        feedback.setAttribute('role', state.error ? 'alert' : 'status');
        if (state.busy) feedback.textContent = tr('loading');
        else if (state.error) {
            const text = document.createElement('p'); text.textContent = state.error;
            const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'issue-btn'; retry.textContent = tr('retry');
            retry.onclick = () => submit(state.submitted, state.submitted.offset);
            feedback.append(text, retry);
        } else if (state.page) {
            feedback.textContent = tr('summary', {query: state.submitted.query, from: state.page.total ? state.page.offset + 1 : 0, to: state.page.offset + state.page.items.length, total: state.page.total});
        }
        const output = container.querySelector('.issue-search-output');
        output.replaceChildren();
        // During another query, previous results remain in memory for recovery,
        // but are not mislabeled as the response to the new query.
        if (!state.page || state.busy || state.error) return;
        if (!state.page.items.length) {
            const empty = document.createElement('p'); empty.className = 'issue-search-empty'; empty.textContent = tr('empty'); output.appendChild(empty); return;
        }
        const list = document.createElement('ol'); list.className = 'issue-search-results';
        for (const hit of state.page.items) {
            const item = document.createElement('li');
            const link = document.createElement('a');
            const issueId = String(hit.issue_id), updateId = hit.update_id === null ? null : String(hit.update_id);
            if (!/^\d+$/.test(issueId) || (updateId !== null && !/^\d+$/.test(updateId))) continue;
            link.href = '/issues/' + issueId + (updateId ? '?update=' + updateId : '');
            link.textContent = hit.title || '#' + issueId;
            link.className = 'issue-search-result-link';
            link.addEventListener('click', event => {
                if (event.button || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
                event.preventDefault();
                history.pushState({issueId: Number(issueId)}, '', link.getAttribute('href'));
                window.renderIssueRoute?.(parseRoute());
            });
            const meta = document.createElement('p'); meta.className = 'issue-search-meta';
            const date = new Date(hit.updated_at);
            meta.textContent = (updateId ? tr('updateRef', {issue: issueId, update: updateId}) : tr('issueRef', {issue: issueId})) + (hit.user ? ' · ' + hit.user : '') + (Number.isFinite(date.getTime()) ? ' · ' + date.toLocaleString(getLang()) : '');
            const snippet = document.createElement('p'); snippet.className = 'issue-search-snippet'; safeSnippet(snippet, hit);
            item.append(link, meta, snippet); list.appendChild(item);
        }
        output.appendChild(list);
        const pagination = document.createElement('nav'); pagination.className = 'issue-search-pagination'; pagination.setAttribute('aria-label', tr('pagination'));
        const previous = document.createElement('button'); previous.className = 'issue-btn'; previous.type = 'button'; previous.textContent = tr('previous'); previous.disabled = state.page.offset === 0;
        previous.onclick = () => submit(state.submitted, Math.max(0, state.page.offset - state.page.limit), true);
        const next = document.createElement('button'); next.className = 'issue-btn'; next.type = 'button'; next.textContent = tr('next'); next.disabled = state.page.next_offset === null;
        next.onclick = () => submit(state.submitted, state.page.next_offset, true);
        pagination.append(previous, next); output.appendChild(pagination);
    }

    window.addEventListener('issue-list-rendered', event => mount(event.detail?.container || document.getElementById('issue-search-slot')));
    if (document.getElementById('issue-search-slot')) mount(document.getElementById('issue-search-slot'));
})();

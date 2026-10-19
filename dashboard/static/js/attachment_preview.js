/* Read-only attachment overlays. Mail HTML arrives allowlist-sanitized by the worker. */
(function () {
    'use strict';
    const tr = key => t('preview.' + key);
    let current = null;
    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }
    async function json(url, signal) {
        const response = await fetch(url, {signal});
        const value = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(value.detail || tr('preview_invalid'));
            error.code = value.code;
            throw error;
        }
        return value;
    }
    function link(label, url) {
        const anchor = node('a', 'preview-button', label);
        anchor.href = url;
        anchor.setAttribute('download', '');
        return anchor;
    }
    function button(label, action) {
        const item = node('button', 'preview-button', label);
        item.type = 'button';
        item.addEventListener('click', action);
        return item;
    }
    function imageLoader(signal) {
        const queue = [], urls = [];
        let running = false;
        signal.addEventListener('abort', () => {
            queue.length = 0;
            urls.forEach(url => URL.revokeObjectURL(url));
        }, {once: true});
        async function next() {
            if (running || signal.aborted || !queue.length) return;
            running = true;
            const {image, url, retry, warning} = queue.shift();
            retry.hidden = true;
            warning.hidden = true;
            try {
                const response = await fetch(url, {signal});
                if (!response.ok) throw new Error('image');
                const blob = await response.blob();
                if (signal.aborted) return;
                const objectUrl = URL.createObjectURL(blob);
                urls.push(objectUrl);
                image.src = objectUrl;
                await image.decode();
                image.hidden = false;
            } catch (error) {
                if (!signal.aborted) {
                    image.hidden = true;
                    warning.hidden = false;
                    retry.hidden = false;
                }
            } finally {
                running = false;
                next();
            }
        }
        return function load(image, url) {
            image.hidden = true;
            const warning = node('span', 'preview-warning', tr('embedded_image_failed'));
            const retry = button(tr('retry'), () => {
                if (!retry.hidden) { retry.hidden = true; queue.push({image, url, retry, warning}); next(); }
            });
            warning.hidden = retry.hidden = true;
            image.after(warning, retry);
            queue.push({image, url, retry, warning});
            next();
        };
    }
    function imageView(content, data, signal, loadImage) {
        const toolbar = node('div', 'preview-image-controls');
        const viewport = node('div', 'preview-image-viewport');
        const image = node('img', 'preview-raster');
        image.alt = data.original_name || tr('image');
        let zoom = 0;
        function scale(value) {
            zoom = Math.max(0, Math.min(4, value));
            image.classList.toggle('preview-zoomed', zoom > 0);
            image.style.width = zoom ? Math.round(data.width * zoom) + 'px' : '';
            image.style.height = zoom ? Math.round(data.height * zoom) + 'px' : '';
            toolbar.dataset.zoom = String(zoom);
        }
        toolbar.append(button(tr('zoomIn'), () => scale(zoom ? zoom * 1.5 : 1)),
            button(tr('zoomOut'), () => scale(zoom > 0.5 ? zoom / 1.5 : 0)),
            button(tr('fit'), () => scale(0)));
        viewport.append(image);
        content.append(toolbar, viewport);
        loadImage(image, data.image_url);
    }
    function mailView(content, data, base, loadImage) {
        const header = node('dl', 'preview-mail-header');
        for (const key of ['subject', 'sender', 'to', 'cc', 'date']) {
            header.append(node('dt', '', tr(key)), node('dd', '', data[key] || tr('missing')));
        }
        const body = node(data.body_format === 'html' ? 'div' : 'pre', 'preview-mail-body');
        const shown = new Set(), pendingImages = [];
        if (data.body_format === 'html') {
            // A second allowlist protects this rendering boundary without parsing
            // unsanitized mail markup anywhere in the browser.
            const template = document.createElement('template');
            template.innerHTML = data.body || '';
            const allowed = new Set(['P','DIV','SPAN','BR','HR','B','STRONG','I','EM','U','S','BLOCKQUOTE','PRE','CODE','UL','OL','LI','TABLE','THEAD','TBODY','TFOOT','TR','TD','TH','H1','H2','H3','H4','H5','H6','A','IMG']);
            template.content.querySelectorAll('*').forEach(element => {
                if (!allowed.has(element.tagName)) { element.remove(); return; }
                const keep = element.tagName === 'IMG' ? ['src','alt'] : element.tagName === 'A' ? ['href'] : [];
                Array.from(element.attributes).forEach(attribute => { if (!keep.includes(attribute.name)) element.removeAttribute(attribute.name); });
                if (element.tagName === 'A') {
                    try { if (!['http:', 'https:', 'mailto:'].includes(new URL(element.getAttribute('href')).protocol)) element.removeAttribute('href'); }
                    catch (_) { element.removeAttribute('href'); }
                }
            });
            template.content.querySelectorAll('img').forEach(image => {
                const src = image.getAttribute('src') || '';
                const suffix = src.slice(base.length);
                if (!src.startsWith(base + '/embedded/') || !/^\/embedded\/\d+\/preview\/image$/.test(suffix)) image.remove();
                else { image.removeAttribute('src'); shown.add(src); pendingImages.push({image, src}); }
            });
            template.content.querySelectorAll('a').forEach(anchor => {
                anchor.rel = 'noopener noreferrer';
                anchor.target = '_blank';
            });
            body.append(template.content);
        } else body.textContent = data.body || tr('emptyBody');
        content.append(header, body);
        pendingImages.slice(0,100).forEach(({image, src}) => loadImage(image, src));
        if (data.attachments.length) {
            const section = node('section', 'preview-embedded');
            section.append(node('h3', '', tr('attachments')));
            const list = node('ul');
            for (const attachment of data.attachments) {
                const row = node('li');
                row.append(node('span', '', attachment.name + ' · ' + attachment.size.toLocaleString() + ' B'));
                if (attachment.download_url) row.append(link(tr('download'), attachment.download_url));
                else row.append(node('span', 'preview-warning', tr('embedded_unsupported')));
                if (attachment.can_preview && attachment.image_url && !shown.has(attachment.image_url)) {
                    const picture = node('img', 'preview-embedded-image');
                    picture.loading = 'lazy';
                    picture.alt = attachment.name;
                    row.append(picture);
                    loadImage(picture, attachment.image_url);
                }
                list.append(row);
            }
            section.append(list);
            content.append(section);
        }
    }
    window.openAttachmentPreview = async function (issueId, attachmentId) {
        if (!Number.isSafeInteger(issueId) || issueId < 1 || !Number.isSafeInteger(attachmentId) || attachmentId < 1) return;
        const previousFocus = current?._previewReturnFocus || document.activeElement;
        if (current) current.close();
        const controller = new AbortController();
        const loadImage = imageLoader(controller.signal);
        const base = `/api/issues/${issueId}/attachments/${attachmentId}`;
        const dialog = node('dialog', 'attachment-preview');
        dialog._previewReturnFocus = previousFocus;
        dialog.setAttribute('aria-labelledby', 'attachment-preview-title');
        const header = node('header', 'preview-header');
        const title = node('h2', '', tr('title'));
        title.id = 'attachment-preview-title';
        const close = button(tr('close'), () => dialog.close());
        close.setAttribute('aria-label', tr('close'));
        close.dataset.previewClose = '';
        header.append(title, close);
        const actions = node('div', 'preview-actions');
        actions.append(link(tr('originalDownload'), base + '/download'));
        const content = node('div', 'preview-content');
        content.setAttribute('aria-busy', 'true');
        const loading = node('p', 'preview-loading', tr('loading'));
        loading.setAttribute('role', 'status');
        content.append(loading);
        dialog.append(header, actions, content);
        dialog.addEventListener('close', () => {
            controller.abort();
            dialog.remove();
            const wasCurrent = current === dialog;
            if (wasCurrent) current = null;
            if (wasCurrent && previousFocus && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
        }, {once: true});
        dialog.addEventListener('keydown', event => {
            if (event.key !== 'Tab') return;
            const focusable = Array.from(dialog.querySelectorAll('button:not([disabled]),a[href],[tabindex="0"]')).filter(element => element.getClientRects().length && !element.hidden);
            const first = focusable[0], last = focusable[focusable.length - 1];
            if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            }
        });
        dialog.addEventListener('click', event => { if (event.target === dialog) {
            const rect = dialog.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
        }});
        document.body.append(dialog);
        current = dialog;
        dialog.showModal();
        close.focus();
        try {
            const metadata = await json(base, controller.signal);
            title.textContent = metadata.original_name;
            const data = await json(base + '/preview', controller.signal);
            if (controller.signal.aborted) return;
            content.replaceChildren();
            for (const warning of data.warnings || []) content.append(node('p', 'preview-warning', tr(warning)));
            if (data.kind === 'image') imageView(content, data, controller.signal, loadImage);
            else if (data.kind === 'msg') mailView(content, data, base, loadImage);
            else throw new Error(tr('preview_unsupported'));
        } catch (error) {
            if (controller.signal.aborted) return;
            const text = error.code && ['preview_unsupported', 'preview_invalid', 'preview_too_large', 'preview_timeout', 'preview_busy', 'embedded_not_found'].includes(error.code) ? tr(error.code) : error.message;
            const message = node('p', 'preview-error', text || tr('preview_invalid'));
            message.setAttribute('role', 'alert');
            content.replaceChildren(message, button(tr('retry'), () => { dialog.close(); window.openAttachmentPreview(issueId, attachmentId); }));
        } finally {
            content.setAttribute('aria-busy', 'false');
        }
    };
})();

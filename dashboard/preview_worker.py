"""Bounded, disposable attachment parser. No application/DB/network imports.

The parent supplies an already authorized, no-follow file descriptor. This is
resource isolation, not a claim that a Python process is an OS sandbox.
"""
import html
import io
import json
import os
import re
import struct
import sys
import warnings
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_INPUT = 25 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_DIMENSION = 10_000
MAX_OUTPUT_DIMENSION = 4096
MAX_IMAGE_OUTPUT = 16 * 1024 * 1024
MAX_ATTACHMENTS = 100
MAX_EMBEDDED = 20 * 1024 * 1024
MAX_AGGREGATE = 50 * 1024 * 1024
MAX_BODY = 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_DEPTH = 16
MAX_FIELD = 8192
RASTER_FORMATS = ('JPEG', 'PNG', 'GIF', 'WEBP', 'BMP')
RASTER_SUFFIXES = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')


class PreviewFailure(Exception):
    def __init__(self, code):
        self.code = code


def bounded(value, limit=MAX_BODY):
    if value is not None and len(value) > limit:
        raise PreviewFailure('preview_too_large')
    return value


def clean_field(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(value or ''))[:MAX_FIELD].strip()


def decode_field(value):
    parts = []
    for part, charset in decode_header(str(value or '')):
        if isinstance(part, bytes):
            try:
                part = part.decode(charset or 'utf-8', errors='replace')
            except LookupError:
                part = part.decode('utf-8', errors='replace')
        parts.append(part)
    return clean_field(''.join(parts))


def image_preview(stream):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            with Image.open(stream, formats=RASTER_FORMATS) as source:
                width, height = source.size
                if width * height > MAX_PIXELS or max(width, height) > MAX_DIMENSION:
                    raise PreviewFailure('preview_too_large')
                animated = getattr(source, 'is_animated', False)
                source.seek(0)
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION))
                # Copy only pixels: remove every inherited EXIF/ICC/XMP field.
                converted = oriented.convert('RGBA' if 'A' in oriented.getbands() or 'transparency' in oriented.info else 'RGB')
                clean = Image.new(converted.mode, converted.size)
                clean.paste(converted)
                output = io.BytesIO()
                clean.save(output, format='PNG')
                payload = bounded(output.getvalue(), MAX_IMAGE_OUTPUT)
                return {'kind': 'image', 'width': clean.width, 'height': clean.height,
                        'original_width': width, 'original_height': height,
                        'warnings': ['first_frame'] if animated else []}, payload
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise PreviewFailure('preview_too_large') from None


def cid_key(value):
    return clean_field(unquote(str(value or ''))).strip('<>')


class MailHTML(HTMLParser):
    """Allowlist serializer: never allow mail-owned resource URLs or CSS."""
    allowed = {'p', 'div', 'span', 'br', 'hr', 'b', 'strong', 'i', 'em', 'u', 's',
               'blockquote', 'pre', 'code', 'ul', 'ol', 'li', 'table', 'thead',
               'tbody', 'tfoot', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'img'}
    discard = {'script', 'style', 'iframe', 'object', 'embed', 'form', 'template', 'noscript', 'svg', 'math', 'head'}
    void = {'br', 'hr', 'img'}

    def __init__(self, cids, base):
        super().__init__(convert_charrefs=True)
        self.cids, self.base = cids, base
        self.out, self.stack = [], []
        self.suppressed = []
        self.resources_removed = False
        self.image_count = 0

    def handle_starttag(self, tag, attrs):
        if self.suppressed:
            # Void HTML elements have no end tag; do not trap following text.
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self.suppressed.append(tag)
            return
        if tag in self.discard:
            if tag != 'embed':
                self.suppressed.append(tag)
            self.resources_removed = True
            return
        if tag not in self.allowed:
            return
        values = dict(attrs)
        safe = ''
        if tag == 'img':
            src = values.get('src') or ''
            index = self.cids.get(cid_key(src[4:])) if src.lower().startswith('cid:') else None
            if index is None or self.image_count >= MAX_ATTACHMENTS:
                self.resources_removed = True
                return
            self.image_count += 1
            safe = ' src="' + self.base + f'/embedded/{index}/preview/image"'
            safe += ' alt="' + html.escape(clean_field(values.get('alt')), quote=True) + '" loading="lazy"'
        elif tag == 'a':
            href = (values.get('href') or '').strip()
            if urlsplit(href).scheme.lower() in {'http', 'https', 'mailto'} and not re.search(r'[\x00-\x20\x7f]', href):
                safe = ' href="' + html.escape(href, quote=True) + '" target="_blank" rel="noopener noreferrer"'
        elif tag in {'td', 'th'}:
            for key in ('colspan', 'rowspan'):
                val = values.get(key, '')
                if val and val.isascii() and val.isdigit() and 0 < int(val) <= 100:
                    safe += f' {key}="{int(val)}"'
        self.out.append('<' + tag + safe + '>')
        if tag not in self.void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag in self.suppressed:
                del self.suppressed[len(self.suppressed) - 1 - self.suppressed[::-1].index(tag):]
            return
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.out.append('</' + current + '>')
                if current == tag:
                    break

    def handle_data(self, data):
        if not self.suppressed:
            self.out.append(html.escape(data))

    def result(self):
        self.out.extend('</' + tag + '>' for tag in reversed(self.stack))
        return bounded(''.join(self.out).encode('utf-8')).decode('utf-8')


def preflight_ole(stream):
    import olefile
    with olefile.OleFileIO(stream) as ole:
        entries = ole.listdir(streams=True, storages=True)
        if len(entries) > MAX_ENTRIES or any(len(p) > MAX_DEPTH for p in entries):
            raise PreviewFailure('preview_too_large')
        top_attachments = {p[0] for p in entries if p[0].startswith('__attach_version1.0_#')}
        if len(top_attachments) > MAX_ATTACHMENTS:
            raise PreviewFailure('preview_too_large')
        total = 0
        for path in ole.listdir(streams=True, storages=False):
            size = ole.get_size(path)
            total += size
            if size > MAX_EMBEDDED or total > MAX_AGGREGATE:
                raise PreviewFailure('preview_too_large')
            name = path[-1].upper()
            if name.endswith('10090102') and '__nameid_version1.0' not in path and size:
                if size > MAX_BODY:
                    raise PreviewFailure('preview_too_large')
                with ole.openstream(path) as rtf:
                    header = rtf.read(16)
                if len(header) < 16:
                    raise PreviewFailure('preview_invalid')
                if struct.unpack('<I', header[4:8])[0] > MAX_BODY:
                    raise PreviewFailure('preview_too_large')
                # The library ignores declared raw_size for compressed data.
                # Input is capped first (worst-case expansion stays bounded).
                import compressed_rtf
                with ole.openstream(path) as rtf:
                    bounded(compressed_rtf.decompress(rtf.read()))
            if len(path) == 1 and name.endswith(('1000001F', '1000001E', '10130102')) and size > MAX_BODY:
                raise PreviewFailure('preview_too_large')
    stream.seek(0)


def read_headers(msg, notes):
    def field(prop, stream=None, header=None):
        try:
            value = getattr(msg, prop)
        except Exception:
            notes.append('header_incomplete')
            value = None
        if not value and stream:
            try:
                value = msg.getStringStream(stream)
            except Exception:
                notes.append('header_incomplete')
        if not value and header:
            try:
                value = decode_field(msg.header.get(header, ''))
            except Exception:
                notes.append('header_incomplete')
        return clean_field(value)
    result = {'subject': field('subject', '__substg1.0_0037', 'Subject'),
              'sender': field('sender', None, 'From'),
              'to': field('to', '__substg1.0_0E04', 'To'),
              'cc': field('cc', '__substg1.0_0E03', 'Cc')}
    try:
        date = msg.date
        if date is None and msg.header.get('Date'):
            date = parsedate_to_datetime(msg.header['Date'])
        result['date'] = date.isoformat() if date else ''
    except Exception:
        notes.append('header_incomplete')
        result['date'] = ''
    return result


def message_body(msg, cids, base, notes):
    # Get raw HTML before derived properties. Decode with explicit replacement.
    raw_html = msg.getStream('__substg1.0_10130102')
    if raw_html is None and msg.compressedRtf:
        try:
            raw_html = msg.htmlBody
        except Exception:
            raw_html = None
    if raw_html:
        bounded(raw_html)
        try:
            encoding = msg.stringEncoding
        except Exception:
            encoding = 'utf-8'
        if raw_html.startswith((b'\xff\xfe', b'\xfe\xff')):
            encoding = 'utf-16'
        # HTML in MSG is commonly UTF-8 even when MAPI string properties use UTF-16.
        elif encoding.lower().replace('-', '').startswith('utf16'):
            encoding = 'utf-8'
        try:
            text = raw_html.decode(encoding, errors='replace')
        except LookupError:
            text = raw_html.decode('utf-8', errors='replace')
        parser = MailHTML(cids, base)
        parser.feed(text)
        parser.close()
        if parser.resources_removed:
            notes.append('resources_removed')
        return 'html', parser.result()
    try:
        text = msg.body
    except Exception:
        text = None
    if not text and msg.compressedRtf:
        from striprtf.striprtf import rtf_to_text
        raw = bounded(msg.rtfBody)
        text = rtf_to_text(raw.decode('latin-1'), errors='replace')
        notes.append('rtf_text')
    return 'text', bounded((text or '').encode('utf-8')).decode('utf-8')


def embedded_payload(attachment):
    from extract_msg.msg_classes.msg import MSGFile
    data = attachment.data
    if isinstance(data, bytes):
        return bounded(data, MAX_EMBEDDED)
    if isinstance(data, MSGFile):
        return bounded(data.exportBytes(), MAX_EMBEDDED)
    raise PreviewFailure('preview_unsupported')


def message_preview(stream, mode, index, base):
    import extract_msg
    from extract_msg.enums import InsecureFeatures
    preflight_ole(stream)
    with extract_msg.openMsg(stream, delayAttachments=True, insecureFeatures=InsecureFeatures.NONE) as msg:
        # Non-mail OLE/MSG classes (contacts, appointments etc.) are a clear fallback.
        if not hasattr(type(msg), 'body') or not str(msg.classType).lower().startswith('ipm.note'):
            raise PreviewFailure('preview_unsupported')
        notes = []
        result = {'kind': 'msg', **read_headers(msg, notes)}
        attachments = msg.attachments
        if len(attachments) > MAX_ATTACHMENTS:
            raise PreviewFailure('preview_too_large')
        items, payloads, cids = [], [], {}
        total = 0
        for position, attachment in enumerate(attachments):
            try:
                payload = embedded_payload(attachment)
            except PreviewFailure as exc:
                if exc.code != 'preview_unsupported':
                    raise
                # OLE attachments that cannot be exported remain visible but unavailable.
                payload = None
            total += len(payload or b'')
            if total > MAX_AGGREGATE:
                raise PreviewFailure('preview_too_large')
            try:
                name = clean_field(attachment.longFilename or attachment.shortFilename)
            except Exception:
                name = ''
            name = name or f'attachment-{position + 1}.bin'
            try:
                mime = clean_field(attachment.mimetype)
            except Exception:
                mime = ''
            can_preview = False
            if payload:
                # Sniff bounded magic; filenames and MIME are untrusted hints only.
                can_preview = payload.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a', b'BM')) or (payload[:4] == b'RIFF' and payload[8:12] == b'WEBP')
            item = {'index': position, 'name': name, 'size': len(payload or b''),
                    'media_type': mime or 'application/octet-stream', 'can_preview': can_preview,
                    'download_url': f'{base}/embedded/{position}/download' if payload is not None else None}
            if can_preview:
                item['image_url'] = f'{base}/embedded/{position}/preview/image'
            elif payload is None:
                notes.append('embedded_unsupported')
            items.append(item)
            payloads.append(payload)
            try:
                cid = cid_key(attachment.cid)
            except Exception:
                cid = ''
            if cid:
                cids[cid] = None if cid in cids or not can_preview else position
        if mode in ('embedded', 'embedded-image'):
            if index < 0 or index >= len(items):
                raise PreviewFailure('embedded_not_found')
            payload = payloads[index]
            if payload is None:
                raise PreviewFailure('preview_unsupported')
            if mode == 'embedded-image':
                return image_preview(io.BytesIO(payload))
            return {'name': items[index]['name'], 'media_type': items[index]['media_type']}, payload
        result['body_format'], result['body'] = message_body(msg, cids, base, notes)
        result['attachments'] = items
        result['warnings'] = sorted(set(notes))
        return result, None


def run(fd, mode, index, base, suffix):
    with os.fdopen(os.dup(fd), 'rb') as stream:
        if os.fstat(stream.fileno()).st_size > MAX_INPUT:
            raise PreviewFailure('preview_too_large')
        magic = stream.read(12)
        stream.seek(0)
        if magic[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            if mode == 'image':
                raise PreviewFailure('preview_unsupported')
            return message_preview(stream, mode, index, base)
        if mode in ('embedded', 'embedded-image'):
            raise PreviewFailure('preview_unsupported')
        try:
            return image_preview(stream)
        except PreviewFailure:
            raise
        except Exception:
            raise PreviewFailure('preview_invalid' if suffix in RASTER_SUFFIXES + ('.msg',) else 'preview_unsupported') from None


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    fd, mode, index, base, suffix, output = sys.argv[1:]
    os.umask(0o077)
    try:
        metadata, payload = run(int(fd), mode, int(index), base, suffix)
        encoded = bounded(json.dumps(metadata, ensure_ascii=False).encode('utf-8'), MAX_JSON)
        if payload is not None and mode != 'metadata':
            Path(output, 'payload.bin').write_bytes(payload)
        Path(output, 'result.json').write_bytes(encoded)
    except BaseException as exc:
        code = exc.code if isinstance(exc, PreviewFailure) else 'preview_invalid'
        if isinstance(exc, MemoryError):
            code = 'preview_too_large'
        Path(output, 'result.json').write_text(json.dumps({'error': code}))


if __name__ == '__main__':
    main()

"""Harmless, synthetic image/MSG fixtures; no runtime/user data."""
import io
import struct


def image_bytes(format='PNG', size=(48, 32)):
    from PIL import Image
    stream = io.BytesIO()
    Image.new('RGB', size, '#167a9a').save(stream, format=format)
    return stream.getvalue()


def message_bytes(kind='html', attachments=None, extra_headers=True, body=None):
    from extract_msg.ole_writer import OleWriter
    writer = OleWriter()
    writer.addEntry('__properties_version1.0', bytes(32) + struct.pack('<IIQ', 0x340D0003, 7, 0x40000))
    writer.addEntry('__nameid_version1.0', storage=True)
    for tag in ('00020102', '00030102', '00040102'):
        writer.addEntry('__nameid_version1.0/__substg1.0_' + tag, b'')

    def string(tag, value, prefix=''):
        writer.addEntry(prefix + '__substg1.0_' + tag + '001F', value.encode('utf-16-le'))
    string('001A', 'IPM.Note')
    string('0037', 'Casos Vorschau ü ✓')
    if extra_headers:
        string('0C1A', 'Test Absender')
        string('0C1F', 'sender@example.invalid')
        string('0E04', 'Reader <reader@example.invalid>')
        string('0E03', 'Copy <cc@example.invalid>')
        string('007D', 'From: Test Absender <sender@example.invalid>\r\nTo: Reader <reader@example.invalid>\r\nCc: Copy <cc@example.invalid>\r\nDate: Mon, 19 Oct 2026 12:00:00 +0200\r\nSubject: Casos Vorschau\r\n')
    if kind == 'text':
        string('1000', body if body is not None else 'Reiner Nachrichtentext ü ✓\nZweite Zeile.')
    elif kind == 'rtf':
        import compressed_rtf
        writer.addEntry('__substg1.0_10090102', compressed_rtf.compress((body or r'{\rtf1\ansi Normaler RTF Text\par Zweite Zeile.}').encode('latin-1')))
    elif kind in ('html', 'html-utf16'):
        writer.addEntry('__substg1.0_10130102', (body or '<p>HTML Nachricht ü ✓ <b>formatiert</b></p><img src="cid:picture"><script>window.previewAttack=1</script><img src="https://tracker.example.invalid/pixel"><iframe src="https://tracker.example.invalid/frame"></iframe><style>@import "https://tracker.example.invalid/style";</style><svg onload="window.previewAttack=2"></svg>').encode('utf-16' if kind == 'html-utf16' else 'utf-8'))
    for index, attachment in enumerate(attachments if attachments is not None else [{'name': 'pixel.png', 'data': image_bytes(), 'mime': 'image/png', 'cid': 'picture'}]):
        prefix = f'__attach_version1.0_#{index:08X}/'
        writer.addEntry(prefix.rstrip('/'), storage=True)
        writer.addEntry(prefix + '__properties_version1.0', bytes(8) + struct.pack('<IIQ', 0x37050003, 7, 1))
        writer.addEntry(prefix + '__substg1.0_37010102', attachment['data'])
        string('3707', attachment['name'], prefix)
        string('370E', attachment.get('mime', 'application/octet-stream'), prefix)
        if attachment.get('cid'):
            string('3712', attachment['cid'], prefix)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()

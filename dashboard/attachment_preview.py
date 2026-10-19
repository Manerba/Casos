"""Authorized preview orchestration; parser work lives in a disposable process."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from dashboard import attachment_service
from dashboard.errors import ApplicationError
from dashboard.preview_worker import MAX_INPUT, MAX_JSON, MAX_EMBEDDED

WORKER = Path(__file__).with_name('preview_worker.py')
WORKER_TIMEOUT = 10
WORKER_SLOTS = threading.BoundedSemaphore(2)
_MESSAGES = {
    'preview_unsupported': (415, 'Für dieses Format ist nur der Download verfügbar.'),
    'preview_invalid': (422, 'Die Datei kann nicht sicher als Vorschau gelesen werden.'),
    'preview_too_large': (413, 'Die Datei überschreitet die Vorschaugrenzen. Der Originaldownload bleibt verfügbar.'),
    'preview_timeout': (422, 'Die Vorschau hat das Zeitlimit überschritten.'),
    'preview_busy': (503, 'Die Vorschau ist ausgelastet. Bitte erneut versuchen.'),
    'embedded_not_found': (404, 'Enthaltener Anhang nicht gefunden.'),
}


def fail(code):
    if code not in _MESSAGES:
        code = 'preview_invalid'
    status, message = _MESSAGES[code]
    raise ApplicationError(status, message, code=code)


def preview(issue_id, attachment_id, user, mode='metadata', index=-1):
    """Return (metadata, optional bounded bytes) after fresh authorization twice."""
    if mode not in {'metadata', 'image', 'embedded', 'embedded-image'}:
        raise ValueError('Unknown preview mode')
    metadata, original = attachment_service.open_attachment(issue_id, attachment_id, user)
    with original:
        if metadata['size'] > MAX_INPUT:
            fail('preview_too_large')
        if not WORKER_SLOTS.acquire(blocking=False):
            fail('preview_busy')
        try:
            base = f'/api/issues/{issue_id}/attachments/{attachment_id}'
            with tempfile.TemporaryDirectory(prefix='casos-preview-') as directory:
                command = [sys.executable, '-I', str(WORKER), str(original.fileno()), mode,
                           str(index), base, Path(metadata['original_name']).suffix.lower(), directory]
                with subprocess.Popen(command, pass_fds=(original.fileno(),), stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      cwd=directory, env={'LANG': 'C.UTF-8', 'TMPDIR': directory},
                                      start_new_session=True) as process:
                    try:
                        returncode = process.wait(timeout=WORKER_TIMEOUT)
                    except BaseException as exc:
                        # Ensure timeout, cancellation and unexpected errors leave no live parser.
                        process.kill()
                        process.wait()
                        if isinstance(exc, subprocess.TimeoutExpired):
                            fail('preview_timeout')
                        raise
                attachment_service.get_attachment(issue_id, attachment_id, user)
                if returncode:
                    fail('preview_too_large' if returncode in (-signal.SIGKILL, -signal.SIGXCPU, -signal.SIGXFSZ) else 'preview_invalid')
                result_file = Path(directory, 'result.json')
                if not result_file.is_file() or result_file.stat().st_size > MAX_JSON:
                    fail('preview_invalid')
                try:
                    result = json.loads(result_file.read_bytes())
                except (ValueError, OSError):
                    fail('preview_invalid')
                if not isinstance(result, dict):
                    fail('preview_invalid')
                if result.get('error'):
                    fail(result['error'])
                result.update(original_name=metadata['original_name'], download_url=metadata['download_url'])
                payload = None
                if mode != 'metadata':
                    binary = Path(directory, 'payload.bin')
                    if not binary.is_file() or binary.stat().st_size > MAX_EMBEDDED:
                        fail('preview_invalid')
                    payload = binary.read_bytes()
                if result.get('kind') == 'image':
                    result['image_url'] = base + '/preview/image'
                return result, payload
        finally:
            WORKER_SLOTS.release()

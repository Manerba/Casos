"""Process-safe first cookie/Fernet secret creation, publication and recovery."""
import multiprocessing
import os
from pathlib import Path
import secrets
import stat
import tempfile
import unittest
from unittest.mock import patch

from dashboard import auth, crypto_utils


def is_key_candidate(fd, path):
    """Limit injected I/O faults to this test's private staging file."""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        target = Path(os.readlink(f'/proc/self/fd/{fd}'))
        return (target.parent == path.parent.resolve()
                and target.name.startswith(f'.{path.name}.')
                and target.name.endswith('.tmp'))
    except OSError:
        return False


def is_key_directory(fd, path):
    try:
        opened, expected = os.fstat(fd), path.parent.stat()
        return (stat.S_ISDIR(opened.st_mode)
                and (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino))
    except OSError:
        return False


def is_key_publication(destination, kwargs, path):
    directory = kwargs.get('dst_dir_fd')
    return (destination == path.name and directory is not None
            and is_key_directory(directory, path))


def secret_worker(path, ready, results, *, pause=None, paused=None, resume=None, first_use='cookie'):
    auth.SECRET_KEY_PATH = Path(path)
    original_token = secrets.token_hex
    original_write, original_link = os.write, os.link
    touched = False

    def wait():
        paused.set()
        if not resume.wait(15):
            raise TimeoutError('Secret test did not release worker')

    def token(size):
        if pause == 'generate' and size == 32:
            wait()
        return original_token(size)

    def write(fd, content):
        nonlocal touched
        if pause == 'partial_write' and not touched and is_key_candidate(fd, auth.SECRET_KEY_PATH):
            touched = True
            written = original_write(fd, content[:7])
            wait()
            return written
        return original_write(fd, content)

    def link(source, destination, **kwargs):
        result = original_link(source, destination, **kwargs)
        if pause == 'published' and is_key_publication(destination, kwargs, auth.SECRET_KEY_PATH):
            wait()
        return result

    ready.set()
    try:
        with patch.object(auth.secrets, 'token_hex', token), patch.object(auth.os, 'write', write), patch.object(auth.os, 'link', link):
            # Exercise the actual two consumers, whichever reaches first use.
            if first_use == 'fernet':
                encrypted = crypto_utils.encrypt('fixture credential')
                signed = auth.sign_token('fixture session')
            else:
                signed = auth.sign_token('fixture session')
                encrypted = crypto_utils.encrypt('fixture credential')
            key = auth.get_secret_key()
        results.put({'key': key, 'signed': signed, 'encrypted': encrypted})
    except Exception as error:
        results.put({'error': f'{type(error).__name__}: {error}'})
    finally:
        results.close()
        results.join_thread()


class SecretKeyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='casos-secret-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'private' / 'secret.key'
        override = patch.object(auth, 'SECRET_KEY_PATH', self.path)
        override.start(); self.addCleanup(override.stop)
        self.context = multiprocessing.get_context('spawn')
        self.results = None
        self.events = []
        self.addCleanup(self.release_resources)

    def release_resources(self):
        # Worker cleanups run first, so no child still needs these semaphores.
        if self.results is not None:
            self.results.close()
            self.results.join_thread()
            self.results = None
        self.events.clear()

    def event(self):
        event = self.context.Event()
        self.events.append(event)
        return event

    def worker(self, **kwargs):
        if self.results is None:
            self.results = self.context.Queue()
        ready = self.event()
        worker = self.context.Process(target=secret_worker, args=(str(self.path), ready, self.results), kwargs=kwargs)
        worker.start()
        def cleanup():
            if worker.is_alive():
                worker.kill()
            worker.join(5)
            worker.close()
        self.addCleanup(cleanup)
        self.assertTrue(ready.wait(10), 'Secret worker did not start')
        return worker

    def result(self, worker):
        worker.join(15)
        self.assertEqual(worker.exitcode, 0)
        result = self.results.get(timeout=2)
        self.assertNotIn('error', result, result)
        return result

    def assert_private_key(self, expected):
        self.assertEqual(self.path.read_text(), expected)
        self.assertTrue(stat.S_ISREG(self.path.stat().st_mode))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.path.parent / '.secret.key.lock').stat().st_mode), 0o600)

    def test_forced_parallel_cookie_and_fernet_first_use_share_one_key(self):
        paused, resume = self.event(), self.event()
        first = self.worker(pause='generate', paused=paused, resume=resume)
        self.assertTrue(paused.wait(10))
        self.assertFalse(self.path.exists())
        second = self.worker(first_use='fernet')
        third = self.worker()
        try:
            second.join(.5); third.join(.5)
            self.assertTrue(second.is_alive(), 'Fernet first use bypassed key creation lock')
            self.assertTrue(third.is_alive(), 'Cookie first use bypassed key creation lock')
        finally:
            resume.set()
        results = [self.result(worker) for worker in (first, second, third)]
        self.assertEqual(len({result['key'] for result in results}), 1)
        key = results[0]['key']
        self.assertEqual(len(key), 64)
        self.assert_private_key(key)
        for result in results:
            self.assertEqual(auth.unsign_token(result['signed']), 'fixture session')
            self.assertEqual(crypto_utils.decrypt(result['encrypted']), 'fixture credential')
        self.assertEqual(auth.get_secret_key(), key)

    def test_existing_key_bytes_are_preserved_and_modes_are_corrected(self):
        self.path.parent.mkdir(mode=0o755)
        self.path.parent.chmod(0o755)
        existing = b'  compatible legacy value\r\n'
        self.path.write_bytes(existing); self.path.chmod(0o644)
        with patch.object(auth.secrets, 'token_hex', side_effect=AssertionError('Must never regenerate')):
            self.assertEqual(auth.get_secret_key(), 'compatible legacy value')
            self.assertEqual(auth.get_secret_key(), 'compatible legacy value')
        self.assertEqual(self.path.read_bytes(), existing)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_empty_existing_key_is_rejected_without_regeneration(self):
        self.path.parent.mkdir()
        for content in (b'', b' \r\n\t'):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with patch.object(auth.secrets, 'token_hex', side_effect=AssertionError('Must never regenerate')):
                    with self.assertRaisesRegex(RuntimeError, 'empty.*restore'):
                        auth.get_secret_key()
                self.assertEqual(self.path.read_bytes(), content)

    def test_symlink_and_nonregular_key_lock_and_directory_are_rejected(self):
        self.path.parent.mkdir()
        target = self.root / 'other'; target.write_text('never touch'); target.chmod(0o644)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):auth.get_secret_key()
        self.assertEqual(target.read_text(), 'never touch')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.path.unlink()
        for kind in ('directory', 'fifo'):
            with self.subTest(kind=kind):
                if kind == 'directory':self.path.mkdir()
                else:os.mkfifo(self.path)
                with self.assertRaisesRegex(RuntimeError, 'regular file'):auth.get_secret_key()
                if kind == 'directory':self.path.rmdir()
                else:self.path.unlink()
        lock = self.path.parent / '.secret.key.lock'
        lock.unlink(); lock.symlink_to(target)
        with self.assertRaises(OSError):auth.get_secret_key()
        self.assertEqual(target.read_text(), 'never touch')
        lock.unlink(); os.mkfifo(lock)
        with self.assertRaisesRegex(RuntimeError, 'regular file'):auth.get_secret_key()
        lock.unlink(); self.path.parent.rmdir()
        real_dir = self.root / 'real'; real_dir.mkdir(mode=0o755)
        self.path.parent.symlink_to(real_dir, target_is_directory=True)
        with self.assertRaises(OSError):auth.get_secret_key()
        self.assertEqual(list(real_dir.iterdir()), [])
        self.assertEqual(stat.S_IMODE(real_dir.stat().st_mode), 0o755)

    def test_killed_partial_writer_never_publishes_and_restart_succeeds(self):
        paused = self.event()
        first = self.worker(pause='partial_write', paused=paused, resume=self.event())
        self.assertTrue(paused.wait(10))
        self.assertFalse(self.path.exists())
        stages = list(self.path.parent.glob('.secret.key.*.tmp'))
        self.assertEqual(len(stages), 1)
        partial = stages[0].read_bytes()
        self.assertEqual(len(partial), 7)
        self.assertEqual(stat.S_IMODE(stages[0].stat().st_mode), 0o600)
        first.kill(); first.join(5)
        result = self.result(self.worker(first_use='fernet'))
        self.assert_private_key(result['key'])
        self.assertEqual(crypto_utils.decrypt(result['encrypted']), 'fixture credential')
        self.assertEqual(stages[0].read_bytes(), partial)

    def test_killed_publisher_keeps_complete_published_key_on_restart(self):
        paused = self.event()
        first = self.worker(pause='published', paused=paused, resume=self.event())
        self.assertTrue(paused.wait(10))
        published = self.path.read_text()
        self.assertEqual(len(published), 64)
        first.kill(); first.join(5)
        result = self.result(self.worker(first_use='fernet'))
        self.assertEqual(result['key'], published)
        self.assert_private_key(published)
        self.assertEqual(auth.unsign_token(result['signed']), 'fixture session')

    def test_write_and_fsync_failures_leave_no_partial_active_key(self):
        real_write, real_fsync, real_link = os.write, os.fsync, os.link
        def partial_then_fail(fd, content):
            if not is_key_candidate(fd, self.path):
                return real_write(fd, content)
            real_write(fd, content[:7])
            raise OSError('injected write failure')
        def fsync_fails(fd):
            if is_key_candidate(fd, self.path):
                raise OSError('injected fsync failure')
            return real_fsync(fd)
        def link_fails(source, destination, **kwargs):
            if is_key_publication(destination, kwargs, self.path):
                raise OSError('injected link failure')
            return real_link(source, destination, **kwargs)
        for operation, failure in (('write', partial_then_fail), ('fsync', fsync_fails), ('link', link_fails)):
            with self.subTest(operation=operation):
                with patch.object(auth.os, operation, side_effect=failure):
                    self.assert_pipe_write_unaffected()
                    with self.assertRaisesRegex(OSError, 'injected'):auth.get_secret_key()
                self.assertFalse(self.path.exists())
                self.assertEqual(list(self.path.parent.glob('.secret.key.*.tmp')), [])
        # Short writes must be completed before publication.
        def short_write(fd, content):
            return real_write(fd, content[:3] if is_key_candidate(fd, self.path) else content)
        with patch.object(auth.os, 'write', side_effect=short_write):
            self.assert_pipe_write_unaffected()
            key = auth.get_secret_key()
        self.assert_private_key(key)
        self.path.unlink()
        def directory_fsync_fails(fd):
            if is_key_directory(fd, self.path):raise OSError('injected directory fsync failure')
            return real_fsync(fd)
        with patch.object(auth.os, 'fsync', side_effect=directory_fsync_fails):
            with self.assertRaisesRegex(OSError, 'directory fsync'):auth.get_secret_key()
        published = self.path.read_text()
        self.assertEqual(len(published), 64)
        self.assertEqual(auth.get_secret_key(), published)
        self.assert_private_key(published)

    def assert_pipe_write_unaffected(self):
        reader, writer = os.pipe()
        try:
            message = b'UNREGISTER:fixture:semaphore\n'
            self.assertEqual(os.write(writer, message), len(message))
            self.assertEqual(os.read(reader, len(message)), message)
        finally:
            os.close(writer)
            os.close(reader)

    def test_fsynced_private_candidate_is_published_without_overwriting_racing_key(self):
        real_link, real_fsync = os.link, os.fsync
        flushed = []
        def fsync(fd):
            real_fsync(fd)
            if is_key_candidate(fd, self.path):flushed.append(os.fstat(fd).st_ino)
        def racing_link(source, destination, **kwargs):
            if not is_key_publication(destination, kwargs, self.path):
                return real_link(source, destination, **kwargs)
            candidate = self.path.parent / source
            self.assertIn(candidate.stat().st_ino, flushed)
            self.assertEqual(stat.S_IMODE(candidate.stat().st_mode), 0o600)
            self.assertEqual(len(candidate.read_bytes()), 64)
            self.path.write_bytes(b'external existing key\n')
            return real_link(source, destination, **kwargs)
        with patch.object(auth.os, 'fsync', side_effect=fsync), patch.object(auth.os, 'link', side_effect=racing_link):
            self.assertEqual(auth.get_secret_key(), 'external existing key')
        self.assertEqual(self.path.read_bytes(), b'external existing key\n')
        self.assertEqual(list(self.path.parent.glob('.secret.key.*.tmp')), [])


if __name__ == '__main__':unittest.main()

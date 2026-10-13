"""Plant links at managed filesystem entry points; external bytes must survive."""
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import hub
import hub_fs
from hub_database import LockedDatabase
from hub_security import open_validated_file, UPLOAD_RETENTION_SECONDS
import test_hub


class ManagedLocations(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def test_upload_cleanup_rejects_swapped_root_and_preserves_arbitrary_files(self):
        outside = self.root / 'outside'; outside.mkdir()
        original = self.h.uploads
        generated = 'a' * 24 + '-old.txt'
        for folder in (original, outside):
            for name in (generated, 'personal.txt'):
                p = folder / name; p.write_text('keep')
                os.utime(p, (1, 1))
        with self.h.lock:
            self.assertEqual(self.h.upload_quota.cleanup(), 1)
        self.assertTrue((original / 'personal.txt').exists())
        original.rename(original.with_name('uploads-safe'))
        original.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            self.h.upload_quota.cleanup()
        self.assertEqual((outside / generated).read_text(), 'keep')
        with self.assertRaises((OSError, ValueError)):
            with hub_fs.open_file(original / ('b' * 24 + '-new.txt'), 'xb'): pass
        self.assertFalse((outside / ('b' * 24 + '-new.txt')).exists())

    def test_upload_cleanup_stays_in_pinned_directory_during_swap(self):
        uploads = self.h.uploads
        outside = self.root / 'outside'; outside.mkdir()
        name = 'c' * 24 + '-old.txt'
        for folder in (uploads, outside):
            p = folder / name; p.write_text('keep'); os.utime(p, (1, 1))
        real = hub_fs.listdir_fd
        swapped = []
        def swap(fd):
            entries = real(fd)
            if name in entries and not swapped:
                swapped.append(True)
                uploads.rename(uploads.with_name('original-uploads'))
                uploads.symlink_to(outside, target_is_directory=True)
            return entries
        with patch.object(hub_fs, 'listdir_fd', side_effect=swap), self.h.lock:
            self.assertEqual(self.h.upload_quota.cleanup(), 1)
        self.assertEqual((outside / name).read_text(), 'keep')
        self.assertFalse((uploads.with_name('original-uploads') / name).exists())

    def test_agent_settings_instruction_and_output_leaf_links_refused(self):
        folder = self.root / 'agents' / self.aid
        outside = self.root / 'outside.txt'; outside.write_text('private')
        for name in ('CLAUDE.md', 'NOTES.md', 'avatar.json', '.claude/settings.json', 'result.png'):
            p = folder / name
            before = p.read_bytes() if p.exists() else None
            p.unlink(missing_ok=True); p.symlink_to(outside)
            with self.subTest(name=name):
                with self.assertRaises((OSError, ValueError)):
                    hub_fs.atomic_write_text(p, 'changed')
                with self.assertRaises((OSError, ValueError)):
                    hub_fs.read_bytes(p)
                with self.assertRaises(hub.HubError):
                    with open_validated_file(p, [folder]): pass
                self.assertEqual(outside.read_text(), 'private')
            p.unlink()
            if before is not None: p.write_bytes(before)

    def test_agent_root_and_settings_directory_links_refused(self):
        folder = self.root / 'agents' / self.aid
        outside = self.root / 'outside'; outside.mkdir()
        for p in (folder / '.claude', folder, self.root / 'agents'):
            safe = p.with_name(p.name + '-original')
            p.rename(safe); p.symlink_to(outside, target_is_directory=True)
            try:
                with self.assertRaises((OSError, ValueError)):
                    hub_fs.atomic_write_text(p / 'new.json', '{}')
                self.assertFalse((outside / 'new.json').exists())
            finally:
                p.unlink(); safe.rename(p)

    def test_codex_final_answer_symlink_and_oversize_refused(self):
        outside = self.root / 'private'; outside.write_text('private')
        last = self.h.data / ('codex-last-' + 'd' * 24 + '.txt')
        last.symlink_to(outside)
        # The absent/symlinked file cannot leak through the answer-file fallback.
        with self.assertRaises(RuntimeError): hub.Hub.parse_codex('', last)
        last.unlink(); last.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError): hub.Hub.parse_codex('', last)


class StartupLocations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=hub.ROOT / 'data')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.outside = self.root / 'outside'; self.outside.mkdir()
        (self.outside / 'keep').write_text('keep')

    def test_startup_rejects_every_managed_subfolder_link(self):
        data = self.root / 'data'; data.mkdir()
        for relative in ('uploads', 'exports', 'teams', 'worktrees', 'swarms',
                         'linked-workspaces', 'managed-pips', 'codex-home-v3', 'nested/child'):
            target = data / relative; target.parent.mkdir(exist_ok=True)
            target.symlink_to(self.outside, target_is_directory=True)
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'cannot start'):
                hub.Hub(self.root, {'detect_engines': False})
            target.unlink()
        data.rmdir() if not list(data.iterdir()) else None
        self.assertEqual((self.outside / 'keep').read_text(), 'keep')

    def test_named_managed_folders_reject_links_even_to_regular_files(self):
        data = self.root / 'data'; data.mkdir()
        for name in ('uploads', 'exports', 'teams', 'worktrees', 'swarms',
                     'linked-workspaces', 'managed-pips', 'codex-home-v3', 'onboarding-run'):
            target = data / name; target.symlink_to(self.outside / 'keep')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'cannot start'):
                hub.Hub(self.root, {'detect_engines': False})
            target.unlink()

    def test_data_symlink_fails_before_chmod_or_database_creation(self):
        mode = self.outside.stat().st_mode
        (self.root / 'data').symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'cannot start'):
            hub.Hub(self.root, {'detect_engines': False})
        self.assertEqual(self.outside.stat().st_mode, mode)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['keep'])

    def test_database_and_sidecar_symlinks_rejected_before_connect(self):
        data = self.root / 'data'; data.mkdir()
        for suffix in ('', '-wal', '-shm', '-journal'):
            p = data / ('hub.sqlite3' + suffix); p.symlink_to(self.outside / 'keep')
            with self.subTest(suffix=suffix), self.assertRaises((OSError, ValueError)):
                LockedDatabase(data / 'hub.sqlite3', threading.RLock())
            p.unlink()
        self.assertEqual((self.outside / 'keep').read_text(), 'keep')

    def test_database_operation_rejects_added_sidecar_link(self):
        data = self.root / 'data'; data.mkdir()
        db = LockedDatabase(data / 'hub.sqlite3', threading.RLock())
        try:
            p = data / 'hub.sqlite3-journal'; p.symlink_to(self.outside / 'keep')
            with self.assertRaises((OSError, ValueError)): db.execute('SELECT 1')
            p.unlink()
        finally: db.close()
        self.assertEqual((self.outside / 'keep').read_text(), 'keep')

"""Regression coverage for descriptor-pinned managed filesystem operations."""

import os
from pathlib import Path
import stat

import tempfile
import unittest

import hub_fs



class FilesystemSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp' if Path('/private/tmp').is_dir() else None)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def raises(self, exception, match=None):
        return self.assertRaisesRegex(exception, match) if match else self.assertRaises(exception)

    def test_regular_read_atomic_write_and_pinned_listing(self):
        data = self.root / 'data'
        hub_fs.mkdir(data / 'uploads', parents=True)
        target = data / 'uploads' / 'file.txt'
        hub_fs.atomic_write_text(target, 'first')
        assert hub_fs.read_text(target) == 'first'
        assert target in hub_fs.listdir(data / 'uploads')
        with self.raises(ValueError, match='limit'):
            hub_fs.read_bytes(target, limit=2)
        directory = hub_fs.open_directory(data / 'uploads')
        try:
            assert hub_fs.listdir_fd(directory) == ['file.txt']
            assert stat.S_ISREG(hub_fs.stat_fd(directory, 'file.txt').st_mode)
            hub_fs.atomic_write_text(target, 'second')
            assert hub_fs.read_text(target) == 'second'
        finally:
            os.close(directory)


    def test_symlinked_ancestor_and_broken_link_are_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'secret').write_text('outside')
        data = self.root / 'data'
        data.mkdir()
        (data / 'uploads').symlink_to(outside, target_is_directory=True)
        for operation in (
            lambda: hub_fs.read_text(data / 'uploads' / 'secret'),
            lambda: hub_fs.atomic_write_text(data / 'uploads' / 'secret', 'changed'),
            lambda: hub_fs.listdir(data / 'uploads'),
            lambda: hub_fs.mkdir(data / 'uploads' / 'new'),
            lambda: hub_fs.open_directory(data / 'uploads'),
            lambda: hub_fs.validate_data_tree(data),
        ):
            with self.raises((OSError, ValueError)):
                operation()
        assert (outside / 'secret').read_text() == 'outside'
        (data / 'uploads').unlink()
        (data / 'uploads').symlink_to(data / 'missing', target_is_directory=True)
        with self.raises((OSError, ValueError)):
            hub_fs.validate_data_tree(data)


    def test_leaf_symlink_fifo_and_hardlink_are_rejected(self):
        parent = self.root / 'uploads'
        parent.mkdir()
        outside = self.root / 'outside'
        outside.write_bytes(b'untouched')
        link = parent / 'link'
        link.symlink_to(outside)
        with self.raises((OSError, ValueError)):
            hub_fs.read_bytes(link)
        with self.raises((OSError, ValueError)):
            hub_fs.atomic_write_bytes(link, b'changed')
        fifo = parent / 'pipe'
        os.mkfifo(fifo)
        with self.raises((OSError, ValueError)):
            hub_fs.read_bytes(fifo)
        hardlink = parent / 'hardlink'
        os.link(outside, hardlink)
        with self.raises(ValueError, match='hard-link'):
            hub_fs.atomic_write_bytes(hardlink, b'changed')
        with self.raises(ValueError, match='hard-linked'):
            hub_fs.open_file(hardlink, 'wb')
        assert outside.read_bytes() == b'untouched'


    def test_unlink_requires_owned_name_and_pinned_directory(self):
        parent = self.root / 'uploads'
        parent.mkdir()
        upload = parent / ('a' * 24 + '-photo.jpg')
        upload.write_bytes(b'photo')
        hub_fs.unlink(upload, generated=True)
        assert not upload.exists()
        other = parent / 'manual.txt'
        other.write_bytes(b'keep')
        with self.raises(PermissionError):
            hub_fs.unlink(other, generated=True)
        fd = hub_fs.open_directory(parent)
        try:
            hub_fs.unlink_fd(fd, 'manual.txt', approved_names={'manual.txt'})
        finally:
            os.close(fd)
        assert not other.exists()


    def test_rename_and_merge_reject_symlink_destinations(self):
        tree = self.root / 'tree'
        main = self.root / 'main'
        tree.mkdir()
        main.mkdir()
        (tree / 'a.txt').write_text('new')
        (main / 'a.txt').write_text('old')
        with hub_fs.prepare_merge(tree, main, [('a.txt', False)]) as prepared:
            hub_fs.apply_merge(prepared)
        assert (main / 'a.txt').read_text() == 'new'
        outside = self.root / 'outside'
        outside.write_text('keep')
        (main / 'b.txt').symlink_to(outside)
        (tree / 'b.txt').write_text('bad')
        with self.raises(ValueError):
            with hub_fs.prepare_merge(tree, main, [('b.txt', False)]):
                pass
        with self.raises(ValueError):
            hub_fs.rename(tree / 'b.txt', main / 'b.txt')
        assert outside.read_text() == 'keep'


    def test_merge_leaf_swap_replaces_link_itself(self):
        tree = self.root / 'tree'
        main = self.root / 'main'
        tree.mkdir()
        main.mkdir()
        (tree / 'replace').write_text('new')
        (main / 'replace').write_text('old')
        (main / 'delete').write_text('old')
        outside = self.root / 'outside'
        outside.write_text('keep')
        with hub_fs.prepare_merge(tree, main, [('replace', False), ('delete', True)]) as prepared:
            (main / 'replace').unlink()
            (main / 'replace').symlink_to(outside)
            (main / 'delete').unlink()
            (main / 'delete').symlink_to(outside)
            hub_fs.apply_merge(prepared)
        assert (main / 'replace').read_text() == 'new'
        assert not (main / 'delete').exists()
        assert outside.read_text() == 'keep'


    def test_merge_replaces_hardlink_without_mutating_other_link(self):
        tree = self.root / 'tree'
        main = self.root / 'main'
        tree.mkdir()
        main.mkdir()
        outside = self.root / 'outside'
        outside.write_text('keep')
        os.link(outside, main / 'target')
        (tree / 'target').write_text('new')
        with hub_fs.prepare_merge(tree, main, [('target', False)]) as prepared:
            hub_fs.apply_merge(prepared)
        assert (main / 'target').read_text() == 'new'
        assert outside.read_text() == 'keep'


    def test_sqlite_guard_rejects_linked_db_and_sidecars(self):
        data = self.root / 'data'
        data.mkdir()
        outside = self.root / 'outside'
        outside.write_bytes(b'other')
        with hub_fs.SQLiteFileGuard(data) as guard:
            (data / 'hub.sqlite3').symlink_to(outside)
            with self.raises(ValueError, match='SQLite'):
                guard.check()
            (data / 'hub.sqlite3').unlink()
            (data / 'hub.sqlite3-wal').symlink_to(outside)
            with self.raises(ValueError, match='SQLite'):
                guard.check()


    def test_auth_symlink_is_restricted(self):
        source = self.root / 'auth-source.json'
        source.write_text('{}')
        account = self.root / 'account'
        account.mkdir()
        hub_fs.symlink(account / 'auth.json', source)
        assert (account / 'auth.json').is_symlink()
        with self.raises(ValueError):
            hub_fs.symlink(account / 'other.json', source)


    def test_ensure_file_and_rmdir_are_pinned(self):
        folder = self.root / 'folder'
        hub_fs.mkdir(folder)
        log = folder / 'hub.log'
        hub_fs.ensure_file(log, 0o600)
        assert stat.S_IMODE(log.stat().st_mode) == 0o600
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'linked-folder'
        link.symlink_to(outside, target_is_directory=True)
        with self.raises(ValueError):
            hub_fs.rmdir(link)
        hub_fs.unlink(log, approved_names={'hub.log'})
        hub_fs.rmdir(folder)
        assert not folder.exists()


    def test_atomic_writer_streams_and_refuses_collision(self):
        upload = self.root / ('a' * 24 + '-image.png')
        with hub_fs.atomic_writer(upload, exclusive=True) as stream:
            stream.write(b'a' * 100_000)
            assert not upload.exists()
        assert upload.read_bytes() == b'a' * 100_000
        with self.raises(FileExistsError):
            with hub_fs.atomic_writer(upload, exclusive=True):
                pass
        assert upload.read_bytes() == b'a' * 100_000
        other = self.root / 'broken'
        with self.raises(RuntimeError):
            with hub_fs.atomic_writer(other) as stream:
                stream.write(b'partial')
                raise RuntimeError('abort')
        assert not other.exists()


    def test_macos_root_aliases_are_narrowly_accepted(self):
        if os.path.islink('/var') and os.readlink('/var') == 'private/var':
            fd = hub_fs.open_directory('/var')
            os.close(fd)
        if os.path.islink('/tmp') and os.readlink('/tmp') == 'private/tmp':
            fd = hub_fs.open_directory('/tmp')
            os.close(fd)

    def test_atomic_writer_never_cleans_an_uncreated_temporary(self):
        from unittest.mock import patch
        temporary = self.root / ('.hub-tmp-' + 'a' * 32)
        temporary.write_bytes(b'preexisting')
        with patch.object(hub_fs.secrets, 'token_hex', return_value='a' * 32):
            with self.assertRaises(FileExistsError):
                with hub_fs.atomic_writer(self.root / 'upload', exclusive=True):
                    pass
        self.assertEqual(temporary.read_bytes(), b'preexisting')

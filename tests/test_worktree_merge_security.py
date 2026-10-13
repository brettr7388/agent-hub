"""Deterministic swaps at the merge/service trust boundary; no live services."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hub_service
import hub_swarms


class MergePaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'data')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.tree, self.main, self.outside = [self.base / n for n in ('tree', 'main', 'outside')]
        for path in (self.tree, self.main, self.outside):
            path.mkdir()
            (path / 'nested').mkdir()
            (path / 'nested' / 'file').write_text(path.name)
            (path / 'nested' / 'deleted').write_text(path.name)

    def test_copy_delete_and_executable_mode(self):
        (self.tree / 'nested/file').chmod(0o755)
        (self.tree / 'new').mkdir()
        (self.tree / 'new/file').write_text('new')
        with hub_swarms._prepare_merge(self.tree, self.main,
                [('nested/file', False), ('nested/deleted', True), ('new/file', False)]) as prepared:
            hub_swarms._apply_merge(prepared)
        self.assertEqual((self.main / 'nested/file').read_text(), 'tree')
        self.assertEqual((self.main / 'nested/file').stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.main / 'nested/deleted').exists())
        self.assertEqual((self.main / 'new/file').read_text(), 'new')

    def test_parent_swaps_after_validation_cannot_redirect_copy_or_delete(self):
        with hub_swarms._prepare_merge(self.tree, self.main,
                [('nested/file', False), ('nested/deleted', True)]) as prepared:
            for root in (self.tree, self.main):
                (root / 'nested').rename(root / 'original')
                (root / 'nested').symlink_to(self.outside / 'nested', target_is_directory=True)
            hub_swarms._apply_merge(prepared)
        self.assertEqual((self.main / 'original/file').read_text(), 'tree')
        self.assertFalse((self.main / 'original/deleted').exists())
        self.assertEqual((self.outside / 'nested/file').read_text(), 'outside')
        self.assertEqual((self.outside / 'nested/deleted').read_text(), 'outside')

    def test_leaf_swaps_after_validation_cannot_redirect_read_write_or_delete(self):
        with hub_swarms._prepare_merge(self.tree, self.main,
                [('nested/file', False), ('nested/deleted', True)]) as prepared:
            for root, name in ((self.tree, 'file'), (self.main, 'file'), (self.main, 'deleted')):
                (root / 'nested' / name).unlink()
                (root / 'nested' / name).symlink_to(self.outside / 'nested' / name)
            hub_swarms._apply_merge(prepared)
        self.assertEqual((self.main / 'nested/file').read_text(), 'tree')
        self.assertFalse((self.main / 'nested/file').is_symlink())
        self.assertFalse((self.main / 'nested/deleted').exists())
        self.assertEqual((self.outside / 'nested/file').read_text(), 'outside')
        self.assertEqual((self.outside / 'nested/deleted').read_text(), 'outside')

    def test_preexisting_links_and_traversal_are_rejected(self):
        for name in ('../outside/nested/file', '/file', '.git/config', 'nested/../file'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                with hub_swarms._prepare_merge(self.tree, self.main, [(name, False)]): pass
        for root in (self.tree, self.main):
            file = root / 'nested/file'
            file.unlink(); file.symlink_to(self.outside / 'nested/file')
            with self.assertRaises((OSError, ValueError)):
                with hub_swarms._prepare_merge(self.tree, self.main, [('nested/file', False)]): pass
            file.unlink(); file.write_text(root.name)
            (root / 'nested').rename(root / 'original')
            (root / 'nested').symlink_to(self.outside / 'nested', target_is_directory=True)
            with self.assertRaises(OSError):
                with hub_swarms._prepare_merge(self.tree, self.main, [('nested/file', False)]): pass
            (root / 'nested').unlink(); (root / 'original').rename(root / 'nested')

    def test_destination_hardlink_does_not_overwrite_other_file(self):
        (self.main / 'nested/file').unlink()
        os.link(self.outside / 'nested/file', self.main / 'nested/file')
        with hub_swarms._prepare_merge(self.tree, self.main, [('nested/file', False)]) as prepared:
            hub_swarms._apply_merge(prepared)
        self.assertEqual((self.outside / 'nested/file').read_text(), 'outside')


class ServicePaths(unittest.TestCase):
    def test_service_rejects_symlink_logs_and_data_without_chmod_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / 'hub'; root.mkdir()
            data = root / 'data'; data.mkdir()
            outside = base / 'outside'; outside.write_text('keep'); outside.chmod(0o644)
            for name in ('hub.stdout.log', 'hub.stderr.log'):
                log = data / name
                log.unlink(missing_ok=True); log.symlink_to(outside)
                with self.assertRaises(OSError):
                    hub_service.handle_service('install', root, platform='darwin', home=base / 'home')
                self.assertEqual(outside.stat().st_mode & 0o777, 0o644)
                self.assertEqual(outside.read_text(), 'keep')
                log.unlink()
            for log in data.iterdir(): log.unlink()
            data.rmdir()
            external_data = base / 'external-data'; external_data.mkdir(mode=0o755)
            data.symlink_to(external_data, target_is_directory=True)
            with self.assertRaises(OSError):
                hub_service.handle_service('install', root, platform='darwin', home=base / 'home')
            self.assertEqual(external_data.stat().st_mode & 0o777, 0o755)

    def test_log_swap_at_open_is_refused_and_fifo_does_not_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / 'hub'; root.mkdir()
            data = root / 'data'; data.mkdir()
            log = data / 'hub.stdout.log'; log.write_text('log')
            outside = base / 'outside'; outside.write_text('keep'); outside.chmod(0o644)
            real_open = os.open
            def swap(name, flags, *args, **kwargs):
                if name == 'hub.stdout.log':
                    log.unlink(); log.symlink_to(outside)
                return real_open(name, flags, *args, **kwargs)
            with patch.object(hub_service.os, 'open', side_effect=swap), self.assertRaises(OSError):
                hub_service.handle_service('install', root, platform='darwin', home=base / 'home')
            self.assertEqual(outside.stat().st_mode & 0o777, 0o644)
            log.unlink(); os.mkfifo(log)
            with self.assertRaises((OSError, ValueError)):
                hub_service.handle_service('install', root, platform='darwin', home=base / 'home')


class MergeOutcome(unittest.TestCase):
    from test_swarms import SwarmCase
    setUp = SwarmCase.setUp
    finished = SwarmCase.finished

    def test_partial_merge_error_keeps_uncertain_outcome_and_blocks_replay(self):
        import subprocess
        import hub
        def git(*args):
            subprocess.run(['git', '-C', str(self.work), *args], check=True, capture_output=True)
        git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
        (self.work / 'base.txt').write_text('base')
        git('add', '.'); git('commit', '-m', 'base')
        self.h.run_engine = lambda *args: 'PASS\nEvidence: fixture\nFiles: none'
        made = self.h.create_swarm({'goal': 'Check merge failure', 'working_dir': str(self.work),
                                    'worktrees': True, 'count': 1})
        worker = self.finished(made['id'])['workers'][0]
        (Path(worker['worktree']) / 'base.txt').write_text('new')
        body = {'id': made['id'], 'action': 'merge', 'worker': worker['agent_id']}
        with patch.object(hub_swarms, '_apply_merge', side_effect=OSError('changed path')):
            with self.assertRaises(hub.HubError) as error:
                self.h.swarm_action(body)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.h.swarm(made['id'])['workers'][0]['outcome'], 'merging')
        with self.assertRaises(hub.HubError):
            self.h.swarm_action(body)
        self.assertEqual((self.work / 'base.txt').read_text(), 'base')

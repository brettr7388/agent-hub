"""Product state and archive checks on a disposable Hub, with fake engines."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import hub
import hub_product
import test_hub


class ProductCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    request = test_hub.HubCase.request
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api

    def test_archive_rejects_symlink_avatar_before_rename(self):
        made = self.h.create_agent({'name': 'Linked Avatar', 'role': 'Help', 'engine': 'claude', 'model': 'haiku'})
        aid = made['agent']['id']
        folder = self.root / 'agents' / aid
        avatar = folder / 'avatar.json'
        outside = self.root / 'outside.json'
        outside.write_text('{"workdir":"outside"}')
        avatar.unlink()
        avatar.symlink_to(outside)
        with self.assertRaises((OSError, ValueError)):
            self.h._release_agent_name(aid)
        self.assertTrue(folder.is_dir())
        self.assertTrue(avatar.is_symlink())
        self.assertEqual(outside.read_text(), '{"workdir":"outside"}')

    def test_archive_avatar_rollback_restores_original_bytes(self):
        made = self.h.create_agent({'name': 'Rollback Avatar', 'role': 'Help', 'engine': 'claude', 'model': 'haiku'})
        aid = made['agent']['id']
        folder = self.root / 'agents' / aid
        avatar = folder / 'avatar.json'
        metadata = json.loads(avatar.read_text())
        metadata['workdir'] = str(folder)
        avatar.write_text(json.dumps(metadata))
        original = avatar.read_bytes()
        real_write = hub_product.atomic_write_bytes
        calls = 0
        def fail_after_write(path, data):
            nonlocal calls
            calls += 1
            real_write(path, data)
            if calls == 1:
                raise OSError('simulated later archive failure')
        with mock.patch.object(hub_product, 'atomic_write_bytes', side_effect=fail_after_write):
            with self.assertRaises(OSError):
                self.h._release_agent_name(aid)
        self.assertEqual(calls, 2)
        self.assertEqual(avatar.read_bytes(), original)
        self.assertTrue(folder.is_dir())

    def test_product_routes_require_session_and_request_header(self):
        for path in ('/api/product', '/api/search?q=violet', '/api/approvals/decision?id=abc'):
            self.assertEqual(self.request(path)[0], 401)
        for path in ('/api/product', '/api/archive', '/api/routines/delete'):
            self.assertEqual(self.request(path, 'POST', {})[0], 401)
        self.cookie = self.login()
        self.assertEqual(self.api('/api/product')[0], 200)
        self.assertEqual(self.api('/api/search?q=violet')[0], 200)
        self.assertEqual(self.api('/api/product', 'POST', {'action': 'pin', 'chat_id': self.cid})[0], 200)
        self.assertEqual(self.api('/api/product', 'POST', {'action': 'pin', 'chat_id': self.cid},
                                  headers={'X-Hub-Request': '0'})[0], 403)

    def test_onboarding_pins_read_continue_and_search_are_durable(self):
        self.assertFalse(self.h.product_state()['getting_started']['completed'])
        self.h.bootstrap({})
        self.assertFalse(self.h.product_state()['getting_started']['completed'])
        self.h.product_action({'action': 'dismiss_getting_started'})
        self.h.product_action({'action': 'pin', 'chat_id': self.cid})
        self.h.product_action({'action': 'continue', 'chat_id': self.cid})
        with self.h.lock:
            self.h.add_message(self.cid, self.aid, 'assistant', 'Find a violet comet')
            self.h.db.commit()
        state = self.h.product_state()
        self.assertEqual(state['pins'], ['agent:guide', self.cid])
        self.assertEqual(state['last_chat'], self.cid)
        self.assertEqual(state['unread'][self.cid], 1)
        self.assertEqual(self.h.search_messages({'q': ['violet']})['results'][0]['text'], 'Find a violet comet')
        with self.h.lock:
            self.h.add_message(self.cid, self.aid, 'assistant',
                'CARD: {"title":"Amber request","text":"Review proof","actions":["Approve"]}')
            self.h.db.commit()
        self.assertIn('Amber request', self.h.search_messages({'q': ['Amber']})['results'][0]['text'])
        with self.h.lock:
            first = self.h.db.execute('SELECT max(id) FROM messages WHERE chat_id=?', (self.cid,)).fetchone()[0]
        with self.h.lock:
            self.h.add_message(self.cid, self.aid, 'assistant', 'Second unread reply')
            self.h.db.commit()
        self.h.product_action({'action': 'mark_read', 'chat_id': self.cid, 'upto_id': first})
        self.assertEqual(self.h.product_state()['unread'][self.cid], 1)
        self.h.product_action({'action': 'mark_read', 'chat_id': self.cid})
        self.assertNotIn(self.cid, self.h.product_state()['unread'])
        self.h.product_action({'action': 'complete_getting_started'})
        self.h.close()
        self.h = hub.Hub(self.root, self.h.config)
        self.addCleanup(self.h.close)
        state = self.h.product_state()
        self.assertTrue(state['getting_started']['completed'])
        self.assertTrue(state['getting_started']['dismissed'])
        self.assertEqual(state['pins'], ['agent:guide', self.cid])
        self.assertEqual(state['last_chat'], self.cid)
        self.assertNotIn(self.cid, state['unread'])

    def test_archive_preserves_agent_files_and_hides_messages(self):
        made = self.h.create_agent({'name': 'Temporary Helper', 'role': 'Help', 'engine': 'claude', 'model': 'haiku'})
        aid = made['agent']['id']
        cid = made['chat_id']
        folder = self.root / 'agents' / aid
        (folder / 'result.png').write_bytes(b'old image')
        with self.h.lock:
            self.h.sync_chats()
            self.h.add_message(cid, aid, 'assistant', 'A unique archive token')
            self.h.db.execute('INSERT INTO messages(chat_id,agent_id,role,text,created,uploads,cards) '
                'VALUES(?,?,?,?,?,?,?)', (cid, aid, 'assistant', 'See ' + str(folder / 'result.png'),
                time.time(), json.dumps([str(folder / 'result.png')]),
                json.dumps([{'media': '/api/file?path=' + str(folder / 'result.png')}])))
            self.h.db.commit()
        routine = self.h.create_routine({'agent_id': aid, 'name': 'Hidden work', 'prompt': 'Test',
            'trigger': 'interval', 'minutes': 5})['routine']
        group = self.h.group({'name': 'Helper group', 'agents': [aid, self.aid]})['chat']['id']
        with self.h.lock:
            self.h.db.execute('INSERT INTO sessions(chat_id,agent_id,sid,t,turns,cwd) VALUES(?,?,?,?,?,?)',
                (cid, aid, 'old-session', time.time(), 1, str(folder)))
            self.h.db.commit()
        archived = self.h.archive({'kind': 'agent', 'id': aid})
        archived_id = archived['archived_id']
        self.assertEqual(archived['files_preserved'], True)
        self.assertEqual(archived['routines_paused'], 1)
        self.assertFalse(next(r for r in self.h.routines()['routines'] if r['id'] == routine['id'])['enabled'])
        self.assertFalse(folder.exists())
        self.assertTrue((self.root / 'agents' / archived_id / 'CLAUDE.md').is_file())
        self.assertTrue(self.h.db.execute('SELECT 1 FROM messages WHERE chat_id=? AND agent_id=?',
            ('agent:' + archived_id, archived_id)).fetchone())
        self.assertEqual(json.loads(self.h.db.execute('SELECT agents FROM chats WHERE id=?',
            ('agent:' + archived_id,)).fetchone()[0]), [archived_id])
        self.assertEqual(json.loads(self.h.db.execute('SELECT agents FROM chats WHERE id=?',
            (group,)).fetchone()[0]), [self.aid])
        self.assertEqual(self.h.db.execute('SELECT cwd FROM sessions WHERE chat_id=? AND agent_id=?',
            ('agent:' + archived_id, archived_id)).fetchone()[0],
            str(self.root / 'agents' / archived_id))
        saved = self.h.db.execute('SELECT text,cards,uploads FROM messages WHERE text LIKE ?',
            ('See %',)).fetchone()
        self.assertTrue(all(str(self.root / 'agents' / archived_id / 'result.png') in saved[k]
                            for k in ('text', 'cards', 'uploads')))
        self.assertEqual(json.loads(self.h.db.execute('SELECT spec FROM routines WHERE id=?',
            (routine['id'],)).fetchone()[0])['agent_id'], archived_id)
        self.assertNotIn(aid, self.h.agents())
        self.assertFalse(any(c['id'] == cid for c in self.h.state()['chats']))
        self.assertEqual(self.h.search_messages({'q': ['unique archive token']})['results'], [])
        replacement = self.h.create_agent({'name': 'Temporary Helper', 'role': 'New work',
            'engine': 'claude', 'model': 'haiku'})
        self.assertEqual(replacement['agent']['id'], aid)
        self.assertTrue(folder.is_dir())
        (folder / 'result.png').write_bytes(b'new image')
        self.assertNotIn(str(folder / 'result.png'), saved['text'])
        self.assertEqual((self.root / 'agents' / archived_id / 'result.png').read_bytes(), b'old image')
        self.h.sync_chats()
        self.assertNotEqual(self.h.chat(cid)['id'], 'agent:' + archived_id)

    def test_group_and_routine_archive_boundaries(self):
        group = self.h.group({'name': 'Scratch', 'agents': [self.aid]})['chat']['id']
        archived = self.h.archive({'kind': 'group', 'id': group})
        self.assertTrue(self.h.db.execute('SELECT 1 FROM chats WHERE id=?', (archived['archived_id'],)).fetchone())
        self.assertFalse(self.h.db.execute('SELECT 1 FROM chats WHERE id=?', (group,)).fetchone())
        self.assertFalse(any(c['id'] == group for c in self.h.state()['chats']))
        self.assertEqual(self.h.group({'name': 'Scratch', 'agents': [self.aid]})['chat']['name'], 'Scratch')
        legacy = self.h.group({'name': 'Legacy Scratch', 'agents': [self.aid]})['chat']['id']
        with self.h.lock:
            self.h.db.execute("INSERT INTO archives(kind,id) VALUES('chat',?)", (legacy,))
            self.h.db.commit()
        self.assertEqual(self.h.group({'name': 'Legacy Scratch', 'agents': [self.aid]})['chat']['name'],
            'Legacy Scratch')

    def test_group_archive_moves_quick_start_pointer(self):
        created = self.h.group({'name': 'Quick start', 'agents': [self.aid]})['chat']['id']
        with self.h.lock:
            self.h._put_setting('quick_start_chat', created)
            self.h.db.commit()
        archived = self.h.archive({'kind': 'group', 'id': created})
        self.assertEqual(self.h._setting('quick_start_chat'), archived['archived_id'])
        routine = self.h.create_routine({'agent_id': self.aid, 'name': 'Scratch', 'prompt': 'Test',
            'trigger': 'interval', 'minutes': 5})['routine']
        self.assertTrue(self.h.delete_routine({'id': routine['id']})['ok'])
        self.assertFalse(any(r['id'] == routine['id'] for r in self.h.routines()['routines']))
        with self.assertRaises(hub.HubError): self.h.delete_routine({'id': 'external-job'})

    def test_approvals_decision_never_claims_posted_from_review(self):
        self.h.config['approvals_url'] = 'http://localhost:4100'
        with mock.patch.object(self.h, 'approvals_request', return_value={'decisions': [
            {'title': 'approvals:abc', 'status': 'approved'}]}):
            self.assertEqual(self.h.approvals_decision('abc')['status'], 'pending')
        with mock.patch.object(self.h, 'approvals_request', return_value={'decisions': [
            {'title': 'approvals:abc', 'status': 'scheduled'}]}) as request:
            self.assertEqual(self.h.approvals_decision('abc')['status'], 'scheduled')
            self.assertEqual(request.call_args.args[0], '/api/decisions?title=approvals%3Aabc')

    def test_swarm_archive_requires_confirmation_and_preserves_dirty_tree_until_confirmed(self):
        work = self.root / 'work'
        work.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(work), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        (work / 'base.txt').write_text('base\n')
        git('add', 'base.txt')
        git('commit', '-m', 'base')
        self.h.run_engine = lambda *args: 'PASS\nEvidence: fixture\nFiles: none'
        made = self.h.create_swarm({'goal': 'Test archive', 'working_dir': str(work),
                                    'worktrees': True, 'count': 1})
        sid = made['id']
        end = time.monotonic() + 5
        while self.h.swarm(sid)['status'] not in ('done', 'gap') and time.monotonic() < end:
            time.sleep(.02)
        worker = self.h.swarm(sid)['workers'][0]
        tree = Path(worker['worktree'])
        subprocess.run(['git', '-C', str(tree), 'mv', 'base.txt', 'renamed.txt'], check=True,
                       capture_output=True)
        with self.assertRaises(hub.HubError): self.h.archive({'kind': 'swarm', 'id': sid})
        with self.assertRaises(hub.HubError): self.h.archive({'kind': 'swarm', 'id': sid, 'confirm': True})
        self.assertTrue(tree.exists())
        self.assertTrue(self.h.archive({'kind': 'swarm', 'id': sid, 'confirm': True,
                                        'confirm_dirty': True})['worktrees_removed'])
        self.assertFalse(tree.exists())
        self.assertFalse(any(s['id'] == sid for s in self.h.swarms()['swarms']))

    def test_legacy_archived_agent_name_is_migrated_on_reuse(self):
        made = self.h.create_agent({'name': 'Old Name', 'role': 'Old', 'engine': 'claude', 'model': 'haiku'})
        aid = made['agent']['id']
        with self.h.lock:
            self.h.sync_chats()
            self.h.add_message(made['chat_id'], aid, 'assistant', 'Old answer')
            self.h.db.execute("INSERT INTO archives(kind,id) VALUES('agent',?)", (aid,))
            self.h.db.execute("INSERT INTO archives(kind,id) VALUES('chat',?)", (made['chat_id'],))
            self.h.db.commit()
        replacement = self.h.create_agent({'name': 'Old Name', 'role': 'New',
            'engine': 'claude', 'model': 'haiku'})
        self.assertEqual(replacement['agent']['id'], aid)
        archived = self.h.db.execute("SELECT id FROM archives WHERE kind='agent' AND id LIKE ?",
            (aid + '-archived-%',)).fetchone()[0]
        self.assertEqual(self.h.db.execute('SELECT text FROM messages WHERE chat_id=?',
            ('agent:' + archived,)).fetchone()[0], 'Old answer')

    def test_scratch_archive_removes_empty_owned_dirs_but_keeps_outputs(self):
        self.h.run_engine = lambda *args: 'PASS\nEvidence: fixture\nFiles: none'
        for keep_output in (False, True):
            made = self.h.create_swarm({'goal': 'Scratch answer', 'working_dir': '',
                'worktrees': False, 'count': 1})
            sid = made['id']
            end = time.monotonic() + 5
            while self.h.swarm(sid)['status'] not in ('done', 'gap') and time.monotonic() < end:
                time.sleep(.02)
            scratch = self.root / 'data' / 'teams' / sid
            if keep_output:
                (scratch / '1' / 'result.txt').write_text('keep')
            result = self.h.archive({'kind': 'swarm', 'id': sid, 'confirm': True})
            self.assertEqual(scratch.exists(), keep_output)
            self.assertEqual(result['scratch_preserved'], keep_output)
            if keep_output:
                self.assertEqual((scratch / '1' / 'result.txt').read_text(), 'keep')


if __name__ == '__main__': unittest.main()

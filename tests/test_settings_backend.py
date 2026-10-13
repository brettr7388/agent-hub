"""PASS10 backend regressions, using disposable data and fake CLIs."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile

import hub
import hub_export
from hub_conversation import pick_by_keywords, valid_emoji, cli_choice
import test_hub


class Pass10Backend(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls
    responses = test_hub.HubCase.responses

    def test_role_routing_and_honest_tie(self):
        ids = [self.h.create_agent({'name': name, 'role': role})['agent']['id'] for name, role in
               [('Writer', 'Writes and edits copy'), ('Coder', 'Fixes software bugs')]]
        self.h.edit_agent({'id': 'researcher', 'role': 'Finds sources and compares evidence'})
        ids.append('researcher')
        agents = self.h.agents()
        self.assertEqual(pick_by_keywords(agents, ids, 'Write a tagline'), 'writer')
        self.assertEqual(pick_by_keywords(agents, ids, 'fix this stack trace'), 'coder')
        self.assertEqual(pick_by_keywords(agents, ids, 'find 3 sources on X'), 'researcher')
        cid = self.h.group({'name': 'Team', 'agents': ids})['chat']['id']
        first = self.send(cid, '@writer hello')
        self.done(first['job_id'])
        with mock.patch('hub.cli_choice', return_value=None) as classify:
            result = self.send(cid, 'What now?')
        classify.assert_called_once()
        self.assertEqual(result['routing'], {'kind': 'tie', 'agent_id': 'writer'})
        self.done(result['job_id'])
        reply = [m for m in self.h.history(cid)['messages'] if m['role'] == 'assistant'][-1]
        self.assertEqual(reply['routing_kind'], 'tie')
        self.assertFalse(reply['best_fit'])

    def test_classifier_timeout_configurable(self):
        with mock.patch.object(self.h, 'isolation_flags', return_value=['--safe-mode']), mock.patch('hub_conversation.run_bounded', return_value=mock.Mock(returncode=1, stdout='')) as run:
            cli_choice({'route_timeout': 15, 'claude_bin': 'fake'}, ['a', 'b'], 'question', hub=self.h)
        self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_edit_instructions_and_permissions_atomic(self):
        agent = self.h.create_agent({'name': 'Draft Writer', 'role': 'Write copy'})['agent']
        aid = agent['id']
        updated = self.h.edit_agent({'id': aid, 'name': 'Writer', 'role': 'Write crisp copy',
                                     'chrome': True, 'draft_only': True, 'use_global_rules': True})['agent']
        self.assertEqual(updated['role'], 'Write crisp copy')
        self.assertTrue(updated['chrome'])
        self.assertTrue(updated['draft_only'])
        instructions = (Path(self.root) / 'agents' / aid / 'CLAUDE.md').read_text()
        self.assertIn('Write crisp copy', instructions)
        self.assertIn('BOTS.md', instructions)
        jid = self.send('agent:' + aid, 'draft')['job_id']
        self.done(jid)
        argv = self.calls(aid)[-1]['argv']
        self.assertEqual(argv[argv.index('--permission-mode') + 1], 'plan')
        self.assertEqual(argv[argv.index('--tools') + 1], 'Read,Glob,Grep')
        self.assertNotIn('--chrome', argv)
        self.assertEqual(self.h.history('agent:' + aid)['messages'][-1]['model'], 'haiku')

    def test_reaction_grace_and_local_only(self):
        self.done(self.send(text='hello')['job_id'])
        answer = next(m for m in self.h.history(self.cid)['messages'] if m['role'] == 'assistant')
        self.assertIsNone(self.h.react({'message_id': answer['id'], 'emoji': '❤️'})['job_id'])
        with mock.patch('hub.threading.Timer') as timer:
            result = self.h.react({'message_id': answer['id'], 'emoji': '👍'})
        self.assertEqual(timer.call_args.args[0], 10)
        prompt = self.h.db.execute('SELECT prompt FROM jobs WHERE id=?', (result['job_id'],)).fetchone()['prompt']
        self.assertIn('go ahead with exactly', prompt)
        self.h.react({'message_id': answer['id'], 'emoji': '👍', 'active': False})
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (result['job_id'],)).fetchone()['status'], 'stopped')

    def test_usage_limit_hold_and_retry(self):
        self.responses(self.aid, [{'exit': 1, 'stderr': 'usage limit reached; resets at 3:00 PM'}, {'result': 'back'}])
        jid = self.send(text='task')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()['status'] == 'held_limit')
        card = [m for m in self.h.history(self.cid)['messages'] if m.get('usage_limit')]
        self.assertEqual(card[-1]['usage_limit']['job_id'], jid)
        self.assertIn('3:00 PM', card[-1]['text'])
        self.h.retry_job({'job_id': jid})
        self.done(jid)
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()['status'], 'done')

    def test_second_job_stays_held_after_limit(self):
        self.responses(self.aid, [{'exit': 1, 'stderr': 'rate limit reached'}, {'result': 'should wait'}])
        first = self.send(text='first')['job_id']
        second = self.send(text='second')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (second,)).fetchone()['status'] == 'held_limit')
        self.assertEqual(len(self.calls(self.aid)), 1)
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (first,)).fetchone()['status'], 'held_limit')

    def test_limit_hold_survives_restart(self):
        self.responses(self.aid, [{'exit': 1, 'stderr': 'quota exceeded'}])
        jid = self.send(text='first')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()['status'] == 'held_limit')
        config = dict(self.h.config)
        self.h.close()
        self.h = hub.Hub(self.root, config, defer_token=True)
        self.addCleanup(self.h.close)
        self.assertIn('claude', self.h.held_engines)
        next_job = self.send(text='later')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (next_job,)).fetchone()['status'] == 'held_limit')
        self.assertEqual(len(self.calls(self.aid)), 1)

    def test_codex_quota_error_is_held(self):
        codex = Path(__file__).with_name('fake_codex.py').resolve()
        self.h.config['codex_bin'] = str(codex)
        created = self.h.create_agent({'name': 'Quota Coder', 'role': 'Code', 'engine': 'codex'})['agent']
        folder = self.root / 'agents' / created['id']
        (folder / 'fake_codex_responses.json').write_text(json.dumps([{'exit': 1, 'stderr': 'rate limit reached'}]))
        jid = self.send('agent:' + created['id'], 'work')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()['status'] == 'held_limit')
        self.assertIn('codex', self.h.held_engines)

    def test_codex_draft_and_alternate_retry(self):
        codex = Path(__file__).with_name('fake_codex.py').resolve()
        self.h.config['codex_bin'] = str(codex)
        self.responses(self.aid, [{'exit': 1, 'stderr': 'usage limit reached'}])
        jid = self.send(text='draft task')['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()['status'] == 'held_limit')
        self.h.edit_agent({'id': self.aid, 'draft_only': True})
        self.h.retry_job({'job_id': jid, 'engine': 'codex'})
        self.done(jid)
        path = self.root / 'agents' / self.aid / 'fake_codex_calls.jsonl'
        call = json.loads(path.read_text().splitlines()[-1])
        argv = call['argv']
        self.assertIn('read-only', argv)
        self.assertIn('approval_policy="never"', argv)
        self.assertNotIn('resume', argv)
        self.assertNotEqual(call['codex_home'], str(self.root / 'fake-source-codex-home'))
        self.assertEqual(self.h.history(self.cid)['messages'][-1]['model'], self.h.config['default_codex_model'])

    def test_exports_exclude_auth_and_secret_files(self):
        self.done(self.send(text='hello')['job_id'])
        archive = zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h)))
        names = archive.namelist()
        self.assertTrue(any(name.startswith('chats/') for name in names))
        self.assertTrue(any(name.endswith('CLAUDE.md') for name in names))
        self.assertFalse(any('auth' in name or '.env' in name or 'secret' in name for name in names))
        self.assertIn('hello', hub_export.markdown_chat(self.h, self.cid).decode())

    def test_markdown_export_includes_card_and_missing_attachment(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                'CARD: {"title":"Publish title","text":"Draft headline","media":"/missing/cover.png","actions":["Approve","Skip"]}',
                uploads=['/missing/attachment.txt'])
            self.h.db.execute('INSERT INTO decisions(message_id,card_index,action) VALUES(?,?,?)', (mid, 0, 'Skip'))
            self.h.db.commit()
        content = hub_export.markdown_chat(self.h, self.cid).decode()
        for required in ('Publish title', 'Draft headline', 'Decision: Skip', 'cover.png', 'attachment.txt'):
            self.assertIn(required, content)

    def test_export_archived_chat_and_all_messages(self):
        cid = self.h.group({'name': 'Archive me', 'agents': [self.aid]})['chat']['id']
        with self.h.lock:
            for number in range(205):
                self.h.add_message(cid, self.aid, 'user', 'line ' + str(number))
            self.h.db.commit()
        self.h.archive({'kind': 'group', 'id': cid})
        archive = zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h)))
        exported = [name for name in archive.namelist() if name.startswith('chats/') and name.endswith('.md')
                    and b'line 204' in archive.read(name)]
        self.assertEqual(len(exported), 1)

    def test_export_routes_require_login(self):
        self.assertEqual(self.request('/api/export/everything')[0], 401)
        self.cookie = self.login()
        status, headers, payload = self.api('/api/export/chat?chat_id=agent:assistant&format=json')
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers.lower())
        self.assertEqual(json.loads(payload)['chat']['id'], self.cid)
        status, _, payload = self.api('/api/export/everything')
        self.assertEqual(status, 200)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(payload)))

    request = test_hub.HubCase.request
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api

    def test_family_emoji(self):
        self.assertTrue(valid_emoji('👨‍👩‍👧‍👦'))

    def test_external_agents_only_instructions_read_only(self):
        external = tempfile.TemporaryDirectory(dir=str(self.root.parent))
        self.addCleanup(external.cleanup)
        folder = Path(external.name) / 'imported'
        folder.mkdir()
        (folder / 'AGENTS.md').write_text('# Imported\n\nResearch private archives')
        self.h.agents_dir = Path(external.name)
        agent = self.h.agents()['imported']
        self.assertTrue(agent['external'])
        self.assertIn('Research private archives', agent['instructions'])
        with self.assertRaises(hub.HubError) as error:
            self.h.edit_agent({'id': 'imported', 'role': 'changed'})
        self.assertEqual(error.exception.status, 403)

    def test_local_agents_md_can_be_edited_and_exported(self):
        folder = self.root / 'agents' / 'codex-notes'
        folder.mkdir()
        (folder / 'AGENTS.md').write_text('# Codex Notes\n\nOriginal instructions')
        self.h.edit_agent({'id': 'codex-notes', 'role': 'Updated instructions'})
        self.assertIn('Updated instructions', (folder / 'AGENTS.md').read_text())
        archive = zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h)))
        self.assertIn('agents/codex-notes/AGENTS.md', archive.namelist())


if __name__ == '__main__': unittest.main()

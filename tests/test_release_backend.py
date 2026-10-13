"""Public launch regression checks, using in-memory HTTP and fake CLIs only."""
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import unittest
from unittest import mock

import hub
import test_hub


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('src', 'href') and value and (value.startswith('/static/') or value == '/manifest.json'):
                self.urls.append(value)


class PublicBackend(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    login = test_hub.HubCase.login
    request = test_hub.HubCase.request
    api = test_hub.HubCase.api

    def test_every_html_and_manifest_asset_is_served_with_mime(self):
        shutil.copytree(hub.ROOT / 'static', self.root / 'static', dirs_exist_ok=True)
        parser = AssetReferences()
        parser.feed((hub.ROOT / 'static' / 'index.html').read_text())
        manifest = json.loads((hub.ROOT / 'static' / 'manifest.json').read_text())
        urls = set(parser.urls + [x['src'] for x in manifest['icons']])
        for name in ('pips.js', 'logo.svg', 'mascot.svg', 'favicon.svg'):
            urls.add('/static/' + name)
        types = {'.js': ('javascript',), '.css': ('text/css',), '.svg': ('image/svg+xml',),
                 '.json': ('application/json',), '.png': ('image/png',), '.woff2': ('font/woff2',)}
        for url in sorted(urls):
            status, headers, content = self.request(url)
            self.assertEqual(status, 200, url)
            self.assertTrue(content, url)
            self.assertTrue(any(t in headers for t in types[Path(url).suffix]), (url, headers))
        for url in ('/static/.env', '/static/../hub.py', '/static/%2e%2e%2fhub.py', '/static/dir%5capp.js'):
            self.assertEqual(self.request(url)[0], 404, url)

    def test_bind_requires_explicit_opt_in_and_https_host_requires_loopback(self):
        for value in ('0.0.0.0', '192.168.1.2', '::'):
            with self.assertRaises(ValueError):
                hub.Hub(self.root, dict(self.h.config, bind=value))
        self.h.config['allowed_origins'] = ['https://device.example.test']
        handler = hub.Handler.__new__(hub.Handler)
        handler.server = type('Server', (), {'hub': self.h, 'server_address': ('127.0.0.1', 4700)})()
        handler.headers = {'Host': 'device.example.test'}
        handler.client_address = ('192.168.1.5', 9000)
        with self.assertRaises(hub.HubError) as error: handler.check_host()
        self.assertEqual(error.exception.status, 403)
        handler.client_address = ('127.0.0.1', 9000)
        self.assertEqual(handler.check_host(), 'device.example.test')

    def test_linked_chat_hide_unhide_and_settings_never_mutate_source(self):
        source = self.root / 'external' / 'My Writer'
        source.mkdir(parents=True)
        (source / 'AGENTS.md').write_text('# Writer\nWrite clear text.')
        self.h.config['external_agent_dirs'] = [str(source.parent)]
        agent = next(a for a in self.h.agents().values() if a.get('linked'))
        aid = agent['id']
        before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        with self.assertRaises(hub.HubError): self.h.edit_agent({'id': aid, 'instructions': 'mutate'})
        self.h.sync_chats()
        sent = self.h.send({'chat_id': 'agent:' + aid, 'text': 'hello', 'request_id': 'linked-chat-test'})
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (sent['job_id'],)).fetchone()[0] == 'done')
        self.assertTrue((self.h.data / 'linked-workspaces' / aid).is_dir())
        self.h.archive({'kind': 'agent', 'id': aid})
        self.assertNotIn(aid, self.h.agents())
        self.assertEqual(self.h.state()['hidden_agents'][0]['id'], aid)
        self.h.unarchive({'id': aid})
        self.assertIn(aid, self.h.agents())
        self.assertTrue(self.h.history('agent:' + aid)['messages'])
        after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_guide_reactions_create_once_through_confirmed_card(self):
        spec = {'action': 'create_agent', 'name': 'Summarizer', 'instructions': 'Summarize articles.'}
        with self.h.lock:
            mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                                    '```agent-hub\n' + json.dumps(spec) + '\n```')
            self.h.db.commit()
        body = {'message_id': mid, 'emoji': '✅', 'active': True, 'request_id': 'guide-reaction-12'}
        preview = self.h.react(body)
        self.assertTrue(preview['confirmation_required'])
        self.assertNotIn('summarizer', self.h.agents())
        result = self.h.react(dict(body, confirm=True))
        self.assertIn('summarizer', self.h.agents())
        self.assertEqual(self.h.react(dict(body, confirm=True)), result)
        self.assertIsNone(result['job_id'])
        messages = self.h.history(self.h.guide_chat())['messages']
        confirmations = [m for m in messages if m['id'] > mid]
        self.assertEqual(len(confirmations), 1)
        self.assertEqual(confirmations[0]['role'], 'system')
        self.assertFalse(confirmations[0]['reply_to'])
        self.assertIn('was created', confirmations[0]['text'])

    def test_plain_reaction_scope_owner_and_draft_rules_acknowledgement(self):
        self.h.save_settings({'owner_name': 'Alex'})
        self.h.edit_agent({'id': 'assistant', 'draft_only': True})
        mid = self.h.add_message(self.cid, self.aid, 'assistant', 'I propose a draft.')
        self.h.db.commit()
        with mock.patch.object(self.h, 'enqueue'):
            result = self.h.react({'message_id': mid, 'emoji': '👍', 'active': True})
        job = self.h.db.execute('SELECT prompt FROM jobs WHERE id=?', (result['job_id'],)).fetchone()[0]
        for phrase in ('Alex reacted', 'only what that message proposed', 'draft-only', 'approval gate', 'Thanks, noted.'):
            self.assertIn(phrase, job)
        with mock.patch.object(self.h, 'run_engine', return_value='NO_REPLY'):
            self.h.execute(result['job_id'])
        last = self.h.history(self.cid)['messages'][-1]
        self.assertEqual(last['role'], 'assistant')
        self.assertEqual(last['text'], 'Thanks, noted.')

    def test_linked_symlink_instructions_are_not_disclosed(self):
        source = self.root / 'linked' / 'helper'
        source.mkdir(parents=True)
        private = self.root / 'private.txt'
        private.write_text('private credential')
        (source / 'CLAUDE.md').symlink_to(private)
        self.h.config['external_agent_dirs'] = [str(source.parent)]
        self.assertFalse(any(a.get('linked') for a in self.h.agents().values()))
        (source / 'CLAUDE.md').unlink()
        (source / 'CLAUDE.md').write_bytes(b'Help with tasks.\xff')
        self.assertTrue(any(a.get('linked') for a in self.h.agents().values()))

    def test_handoff_includes_full_source_answer(self):
        other = 'reviewer'
        self.h.edit_agent({'id': other, 'draft_only': True})
        cid = self.h.group({'name': 'Recipe', 'agents': [self.aid, other]})['chat']['id']
        answer = 'A complete recipe: ' + 'Mix ingredients. ' * 40 + '\n@@handoff reviewer: Improve the recipe.'
        with mock.patch.object(self.h, 'enqueue'):
            sent = self.h.send({'chat_id': cid, 'text': '@assistant Make a recipe', 'request_id': 'handoff-pass12'})
        with mock.patch.object(self.h, 'run_engine', side_effect=[answer, 'Add a crisp side.']) as runner:
            self.h.execute(sent['job_id'])
        prompt = runner.call_args_list[1].args[2]
        self.assertIn(answer.split('\n@@handoff')[0].rstrip(), prompt)
        self.assertIn('Original user request:\n@assistant Make a recipe', prompt)
        self.assertNotIn('@@handoff', prompt)

    def test_home_boundary_sensitive_paths_and_outside_install_default(self):
        for path in ('/private/tmp', str(Path.home() / '.ssh')):
            with self.assertRaises(hub.HubError): self.h.create_swarm({'goal': 'test', 'working_dir': path, 'count': 1})
        with mock.patch('hub_guide.Path.home', return_value=Path('/')):
            with self.assertRaises(hub.HubError):
                self.h.create_agent({'name': 'Unsafe', 'role': 'x', 'workdir': str(self.root / '.codex')})
        with mock.patch('hub.Path.home', return_value=self.root / 'home'):
            (self.root / 'home').mkdir()
            created = self.h.create_agent({'name': 'Portable', 'role': 'x'})['agent']
            self.assertEqual(created['workdir'], str(self.root / 'home'))
            self.h.edit_agent({'id': created['id'], 'workdir': created['workdir']})

    def test_task_answer_strips_protocol_and_scratch_has_no_merge(self):
        self.assertEqual(self.h.worker_answer('**Answer:** A practical plan.\n**Status:** PASS\n**Evidence:** checked\n**Files:** None.'), 'A practical plan.')
        with mock.patch.object(self.h, 'enqueue'):
            task = self.h.create_swarm({'goal': 'Compare ideas', 'count': 1})
        got = self.h.swarm(task['swarm']['id']) if 'swarm' in task else self.h.swarm(task['id'])
        self.assertFalse(got['workers'][0]['has_changes'])


if __name__ == '__main__': unittest.main()

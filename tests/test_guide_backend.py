"""Guide proposals stay drafts until an authenticated owner acts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import hub
import test_hub


class GuideBackend(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request
    def test_guide_first_run_once_and_archive(self):
        guide = self.h.agents()['guide']
        self.assertTrue(guide['guide'])
        self.assertFalse(guide['draft_only'])
        self.assertEqual(guide['model'], 'haiku')
        self.assertEqual(guide['pip_style']['accessory'], 'compass')
        self.assertIn('agent:guide', self.h.product_state()['pins'])
        history = self.h.history('agent:guide')['messages']
        self.assertEqual(history[0]['cards'][0]['kind'], 'guide_starters')
        self.assertEqual(len(history[0]['cards'][0]['starters']), 4)
        archived = self.h.archive({'kind': 'agent', 'id': 'guide'})['archived_id']
        self.assertNotEqual(self.h._setting('guide_agent_id'), 'guide')
        ordinary = self.h.create_agent({'name': 'Guide', 'role': 'A normal helper.'})['agent']
        self.assertFalse(ordinary['guide'])
        with self.h.lock:
            mid = self.h.add_message('agent:guide', 'guide', 'assistant',
                '```agent-hub\n{"action":"create_agent","name":"Injected","instructions":"x"}\n```')
            self.h.db.commit()
        self.assertEqual(json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0]), [])
        self.h.close()
        self.h = hub.Hub(self.root, dict(self.h.config), defer_token=True)
        self.assertFalse(any(a['guide'] for a in self.h.agents().values()))
        self.assertFalse(self.h.agents()['guide']['guide'])
        self.assertTrue(self.h._setting('guide_created'))
        self.h.unarchive({'id': archived})
        self.assertIn('agent:' + archived, self.h.product_state()['pins'])

    def test_existing_custom_guide_is_not_trusted(self):
        root = self.root / 'upgrade'
        (root / 'agents' / 'guide').mkdir(parents=True)
        (root / 'agents' / 'guide' / 'CLAUDE.md').write_text('# Guide\n\nUser custom agent')
        (root / 'agents' / 'guide' / 'avatar.json').write_text(json.dumps({'name': 'Guide', 'draft_only': False}))
        other = hub.Hub(root, dict(self.h.config), defer_token=True)
        self.addCleanup(other.close)
        self.assertFalse(other.agents()['guide']['guide'])
        starter = next(a for a in other.agents().values() if a['guide'])
        self.assertEqual(starter['id'], 'guide-starter')
        with other.lock:
            mid = other.add_message('agent:guide', 'guide', 'assistant',
                '```agent-hub\n{"action":"create_agent","name":"Injected","instructions":"x"}\n```')
            other.db.commit()
        self.assertEqual(json.loads(other.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0]), [])

    def test_thumbs_up_proposal_has_one_confirmation_message(self):
        spec = {'action': 'create_agent', 'name': 'Writer', 'instructions': 'Write clearly.'}
        mid = self.h.add_message('agent:guide', 'guide', 'assistant',
            'Here is a writing Pip.\n```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        before = len(self.h.history('agent:guide')['messages'])
        preview = self.h.react({'message_id': mid, 'emoji': '👍', 'request_id': 'guide-react-preview'})
        self.assertTrue(preview['confirmation_required'])
        self.assertEqual(len(self.h.history('agent:guide')['messages']), before)
        result = self.h.react({'message_id': mid, 'emoji': '👍', 'confirm': True,
                               'request_id': 'guide-react-confirm'})
        self.assertEqual(result['guide_result']['card']['status'], 'created')
        self.assertEqual(result['guide_result']['result']['agent']['name'], 'Writer')
        added = self.h.history('agent:guide')['messages'][before:]
        self.assertEqual([m['text'] for m in added], ['Writer was created.'])

    def test_archiving_created_pip_updates_only_its_guide_receipt(self):
        mids = []
        for name in ('Writer', 'Editor'):
            spec = {'action': 'create_agent', 'name': name, 'instructions': 'Help with text.'}
            mid = self.h.add_message('agent:guide', 'guide', 'assistant',
                '```agent-hub\n' + json.dumps(spec) + '\n```')
            self.h.db.commit()
            self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
            mids.append(mid)
        self.h.archive({'kind': 'agent', 'id': 'writer'})
        history = self.h.history('agent:guide')['messages']
        receipts = [message['text'] for message in history if message['role'] == 'system']
        self.assertIn('Creation undone.', receipts)
        self.assertIn('Editor was created.', receipts)
        self.assertNotIn('Writer was created.', receipts)
        cards = {message['id']: message['cards'] for message in history}
        self.assertEqual(cards[mids[0]][0]['status'], 'pending')
        self.assertEqual(cards[mids[1]][0]['status'], 'created')

    def test_guide_browser_proposal_instructions_include_account_and_send_rules(self):
        from hub_guide import GUIDE_ROLE
        self.assertIn('use only the Pip browser for accounts', GUIDE_ROLE)
        self.assertIn('ask the owner before sending', GUIDE_ROLE)

    def test_archiving_created_group_updates_its_guide_receipt(self):
        self.h.create_agent({'name': 'Critic', 'role': 'Review text.'})
        spec = {'action': 'create_group', 'name': 'Reviewers', 'agents': ['Assistant', 'Critic']}
        mid = self.h.add_message('agent:guide', 'guide', 'assistant',
            '```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.h.archive({'kind': 'group', 'id': result['result']['chat']['id']})
        history = self.h.history('agent:guide')['messages']
        self.assertEqual(history[-1]['text'], 'Creation undone.')
        card = next(message for message in history if message['id'] == mid)['cards'][0]
        self.assertEqual(card['status'], 'pending')

    def test_first_logged_in_engine_uses_smallest_supported_model(self):
        catalog = {'claude': {'available': True, 'authenticated': 'login_required'},
                   'codex': {'available': True, 'authenticated': 'ready'}}
        (self.root / 'codex-ready').mkdir()
        with mock.patch.object(hub.Hub, 'engine_catalog', return_value=catalog):
            other = hub.Hub(self.root / 'codex-ready', dict(self.h.config), defer_token=True)
        self.addCleanup(other.close)
        guide = next(a for a in other.agents().values() if a['guide'])
        self.assertEqual((guide['engine'], guide['model']), ('codex', 'gpt-6-luna'))
        self.assertTrue(guide['use_global_rules'])
        self.assertFalse(list(other.db.execute('SELECT id FROM jobs')))

    def test_team_modes_only_launch_after_approval_and_edited_options_survive(self):
        for mode, shape in [('split', 'partition'), ('race', 'race'), ('roles', 'roles')]:
            spec = {'action': 'start_team_task', 'agents': ['Assistant'], 'mode': mode,
                    'task': 'Compare two ways to organize a small project.'}
            with self.h.lock:
                mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                    '```agent-hub\n' + json.dumps(spec) + '\n```')
                self.h.db.commit()
            with mock.patch.object(self.h, 'create_swarm', return_value={'chat_id': 'group:review'}) as launch:
                self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'edit'})
                launch.assert_not_called()
                edited = dict(spec, team_options={'workers': [{'source_agent_id': 'assistant',
                    'role': 'Reviewer', 'slice': 'Compare maintenance costs.', 'engine': 'claude', 'model': 'haiku'}],
                    'working_dir': '', 'worktrees': False, 'rubric': ['Correct', 'Clear', 'Practical']})
                self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create', 'proposal': edited})
                payload = launch.call_args.args[0]
                self.assertEqual(payload['shape'], shape)
                self.assertEqual(payload['workers'][0]['slice'], 'Compare maintenance costs.')
                self.assertEqual(payload['rubric'], ['Correct', 'Clear', 'Practical'])
                self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
                self.assertEqual(launch.call_count, 1)

    def test_interrupted_creation_is_never_replayed(self):
        spec = {'action': 'create_agent', 'name': 'Interruption', 'instructions': 'Write clearly.'}
        with self.h.lock:
            mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                '```agent-hub\n' + json.dumps(spec) + '\n```')
            self.h.db.commit()
        with mock.patch.object(self.h, '_create_guide_proposal', side_effect=OSError('simulated disk failure')) as create:
            with self.assertRaises(OSError):
                self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
            result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
            self.assertEqual(result['card']['status'], 'interrupted')
            self.assertEqual(create.call_count, 1)

    def test_parser_rejects_wrong_source_and_bad_data(self):
        valid = {'action': 'create_agent', 'name': 'Writer', 'emoji': '✍️', 'title': 'Writes',
                 'instructions': 'Write clearly.', 'engine': 'claude', 'model': 'haiku', 'workdir': None}
        fence = 'Here is a draft.\n```agent-hub\n' + json.dumps(valid) + '\n```'
        with self.h.lock:
            guide = self.h.add_message('agent:guide', 'guide', 'assistant', fence)
            other = self.h.add_message('agent:assistant', 'assistant', 'assistant', '```agent-hub\n' + json.dumps(valid) + '\n```')
            user = self.h.add_message('agent:guide', 'guide', 'user', fence)
            self.h.db.commit()
        self.assertEqual(self.h.history('agent:guide')['messages'][-2]['cards'][0]['proposal']['name'], 'Writer')
        self.assertNotIn('agent-hub', self.h.history('agent:guide')['messages'][-2]['text'])
        self.assertEqual(self.h.history('agent:assistant')['messages'][-1]['cards'], [])
        self.assertEqual(self.h.history('agent:guide')['messages'][-1]['cards'], [])
        self.assertEqual(len(json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (guide,)).fetchone()[0])), 1)
        self.assertTrue(other and user)
        bad = [
            '{broken', json.dumps(dict(valid, instructions='x' * 8001)),
            json.dumps(dict(valid, model='bogus')),
            json.dumps(dict(valid, workdir='/private/tmp')),
        ]
        for raw in bad:
            clean, cards = self.h.parse_guide_reply('```agent-hub\n' + raw + '\n```')
            self.assertEqual(cards, [])
            if raw == '{broken':
                self.assertEqual(clean, '```agent-hub\n' + raw + '\n```')
            else:
                self.assertIn('proposal', clean.lower())
                self.assertNotIn('agent-hub', clean)

    def test_create_edit_dismiss_and_repeat(self):
        self.cookie = self.login()
        spec = {'action': 'create_agent', 'name': 'Writer', 'emoji': '✍️', 'title': 'Writes',
                'instructions': 'Write clearly.', 'engine': 'claude', 'model': 'haiku'}
        with self.h.lock:
            mid = self.h.add_message('agent:guide', 'guide', 'assistant',
                '```agent-hub\n' + json.dumps(spec) + '\n```\n```agent-hub\n' +
                json.dumps(dict(spec, name='Proofreader')) + '\n```')
            self.h.db.commit()
        status, _, body = self.api('/api/guide/proposal', 'POST', {'message_id': mid, 'index': 0, 'action': 'edit'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['proposal']['name'], 'Writer')
        self.assertNotIn('writer', self.h.agents())
        status, _, body = self.api('/api/guide/proposal', 'POST', {'message_id': mid, 'index': 0,
            'action': 'create', 'proposal': dict(spec, name='Editor')})
        self.assertEqual(status, 200)
        self.assertIn('editor', self.h.agents())
        self.assertEqual(json.loads(body)['card']['status'], 'created')
        self.assertTrue(json.loads(self.api('/api/guide/proposal', 'POST', {'message_id': mid, 'index': 0,
            'action': 'create'})[2])['duplicate'])
        self.assertEqual(self.api('/api/guide/proposal', 'POST', {'message_id': mid, 'index': 1,
            'action': 'dismiss'})[0], 200)
        self.assertNotIn('proofreader', self.h.agents())
        self.assertEqual(self.h.history('agent:guide')['messages'][-2]['cards'][1]['status'], 'dismissed')

    def test_nested_group_and_pip_assignment(self):
        self.cookie = self.login()
        nested = {'action': 'create_group', 'name': 'New team', 'emoji': '👥', 'agents': [
            'Assistant', {'action': 'create_agent', 'name': 'Analyst', 'emoji': '🔎', 'title': 'Analyzes',
                          'instructions': 'Analyze evidence.', 'engine': 'claude', 'model': 'haiku'}]}
        with self.h.lock:
            mid = self.h.add_message('agent:guide', 'guide', 'assistant', '```agent-hub\n' + json.dumps(nested) + '\n```')
            self.h.db.commit()
        result = json.loads(self.api('/api/guide/create-all', 'POST', {'message_id': mid})[2])
        self.assertEqual(result['results'][0]['result']['chat']['agents'], ['assistant', 'analyst'])
        self.assertTrue(json.loads(self.api('/api/guide/create-all', 'POST', {'message_id': mid})[2])['results'][0]['duplicate'])
        style = {'palette': 'teal', 'accessory': 'magnifier', 'eyes': 'wide', 'antenna': 'star', 'visor': 'squircle'}
        original_style = self.h.agents()['analyst']['pip_style']
        self.assertIsNotNone(original_style)
        self.assertEqual(json.loads(self.api('/api/agents/pips', 'POST', {'assignments': [{'id': 'analyst', 'pip_style': style}]})[2])['assigned'], [])
        style = original_style
        self.assertEqual(self.h.agents()['analyst']['pip_style'], style)
        self.assertEqual(json.loads(self.api('/api/agents/pips', 'POST', {'assignments': [{'id': 'analyst', 'pip_style': dict(style, palette='red')}]})[2])['assigned'], [])
        self.assertEqual(self.h.agents()['analyst']['pip_style'], style)
        red = dict(style, palette='red')
        with self.assertRaises(hub.HubError):
            self.h.edit_agent({'id': 'analyst', 'pip_style': red, 'instructions': ''})
        self.assertEqual(self.h.agents()['analyst']['pip_style'], style)
        self.h.edit_agent({'id': 'analyst', 'pip_style': red, 'avatar_style': 'emoji'})
        self.assertEqual(self.h.agents()['analyst']['pip_style'], red)
        self.assertEqual(self.h.agents()['analyst']['avatar_style'], 'emoji')
        old = self.h.archive({'kind': 'agent', 'id': 'analyst'})['archived_id']
        self.assertEqual(self.h._setting('pip_style:' + old), red)
        self.assertIsNone(self.h._setting('pip_style:analyst'))
        recreated = self.h.create_agent({'name': 'Analyst', 'role': 'New analyst.'})['agent']
        self.assertIsNotNone(recreated['pip_style'])

    def test_demo_first_prompt_and_archive(self):
        self.cookie = self.login()
        response = json.loads(self.api('/api/guide/demo', 'POST', {})[2])
        self.assertEqual(len(response['cards']), 3)
        self.assertTrue(json.loads(self.api('/api/guide/demo', 'POST', {})[2])['duplicate'])
        original = self.h.create_agent
        def seeded(body):
            created = original(body)
            if created['agent']['id'] == 'chef':
                (self.root / 'agents' / 'chef' / 'fake_responses.json').write_text(
                    json.dumps([{'result': 'Try pasta with vegetables.\n@@handoff critic: Check this dinner idea.'}]))
            if created['agent']['id'] == 'critic':
                (self.root / 'agents' / 'critic' / 'fake_responses.json').write_text(
                    json.dumps([{'result': 'Add a protein and a crisp side.'}]))
            return created
        with mock.patch.object(self.h, 'create_agent', side_effect=seeded):
            result = json.loads(self.api('/api/guide/create-all', 'POST', {'message_id': response['message_id']})[2])
        group = result['results'][-1]['result']['chat']['id']
        self.assertEqual(result['demo_chat_id'], group)
        test_hub.poll(lambda: self.h.db.execute('SELECT count(*) FROM jobs WHERE chat_id=? AND status="done"', (group,)).fetchone()[0] > 0)
        self.assertIn('Chef', self.h.history(group)['messages'][0]['text'])
        messages = self.h.history(group)['messages']
        self.assertTrue(any(m['agent_id'] == 'chef' and m['best_fit'] for m in messages))
        test_hub.poll(lambda: any(m['agent_id'] == 'critic' and m['role'] == 'assistant'
                                  for m in self.h.history(group)['messages']))
        self.assertFalse(any('@@handoff' in m['text'] for m in self.h.history(group)['messages']))
        self.assertFalse(any(c.get('_handoff') for m in self.h.history(group)['messages'] for c in m['cards']))
        self.assertTrue(any(m['agent_id'] == 'critic' and m['role'] == 'assistant' for m in self.h.history(group)['messages']))
        self.assertTrue(next(c for c in self.h.state()['chats'] if c['id'] == group)['demo'])
        self.assertEqual(self.api('/api/guide/demo/archive', 'POST', {})[0], 200)
        self.assertNotIn('chef', self.h.agents())
        self.assertNotIn('critic', self.h.agents())

    def test_demo_uses_unused_names_and_tracks_partial_create(self):
        self.cookie = self.login()
        self.h.create_agent({'name': 'Chef', 'role': 'Existing chef.'})
        self.h.create_agent({'name': 'Critic', 'role': 'Existing critic.'})
        demo = json.loads(self.api('/api/guide/demo', 'POST', {})[2])
        names = [c['proposal']['name'] for c in demo['cards'][:2]]
        self.assertEqual(names, ['Demo Chef', 'Demo Critic'])
        self.assertEqual(demo['cards'][2]['proposal']['agents'], names)
        mid = demo['message_id']
        first = json.loads(self.api('/api/guide/proposal', 'POST', {'message_id': mid, 'index': 0, 'action': 'create'})[2])
        self.assertEqual(first['card']['status'], 'created')
        all_result = json.loads(self.api('/api/guide/create-all', 'POST', {'message_id': mid})[2])
        self.assertTrue(all_result['results'][0]['duplicate'])
        group = all_result['demo_chat_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT count(*) FROM jobs WHERE chat_id=? AND status IN ("done","error")', (group,)).fetchone()[0] > 0)
        self.assertEqual(self.api('/api/guide/demo/archive', 'POST', {})[0], 200)
        self.assertNotIn('demo-chef', self.h.agents())
        self.assertNotIn('demo-critic', self.h.agents())
        self.assertIn('chef', self.h.agents())
        self.assertIn('critic', self.h.agents())


if __name__ == '__main__': unittest.main()

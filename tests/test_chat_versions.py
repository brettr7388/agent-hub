"""Direct chats, editing branches, and live streaming metadata with fake CLIs."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_hub


class ChatVersionsTest(test_hub.HubCase):
    def test_group_edit_switch_search_and_quote_parent(self):
        group = self.h.group({'name': 'Pair', 'agents': ['assistant', 'researcher']})['chat']['id']
        self.responses('assistant', [{'result': 'First group answer'}, {'result': 'Old second answer'},
                                          {'result': 'Edited answer'}])
        first = self.send(group, '@assistant first group request')
        self.done(first['job_id'])
        answer_id = next(m['id'] for m in self.h.history(group)['messages'] if m['role'] == 'assistant')
        second = self.send(group, '@assistant old second group request', reply_to=answer_id)
        self.done(second['job_id'])
        original = self.h.history(group)['active_version']
        edit = self.h.edit_chat_message({'chat_id': group, 'message_id': second['message_id'],
                                         'text': '@assistant revised second request', 'request_id': 'group-edit-0001'})
        self.done(edit['job_id'])
        current = self.h.history(group)
        edited_user = next(m for m in current['messages'] if m['id'] == edit['message_id'])
        self.assertEqual(edited_user['reply_to'], answer_id)
        self.assertNotIn('old second group request', [m['text'] for m in current['messages']])
        self.assertEqual(self.h.search_messages({'q': ['old second group request']})['results'], [])
        self.assertIn('First group answer', self.calls()[-1]['argv'][self.calls()[-1]['argv'].index('-p') + 1])
        restored = self.h.switch_chat_version({'chat_id': group, 'version_id': original})
        self.assertIn('@assistant old second group request', [m['text'] for m in restored['messages']])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM sessions WHERE chat_id=?', (group,)).fetchone()[0], 0)
        self.cookie = self.login()
        self.assertEqual(self.api('/api/chats/delete', 'POST', {'chat_id': group})[0], 400)

    def test_edit_collision_and_expired_upload_rollback(self):
        sent = self.send(text='original')
        self.done(sent['job_id'])
        with self.assertRaises(test_hub.hub.HubError) as collision:
            self.h.edit_chat_message({'chat_id': self.cid, 'message_id': sent['message_id'],
                                      'text': 'replacement', 'request_id': 'request-00000001'})
        self.assertEqual(collision.exception.status, 409)
        original = self.h.history(self.cid)['active_version']
        expired = self.h.add_message(self.cid, self.aid, 'user', 'attachment request',
                                     uploads=[str(self.h.uploads / 'expired.png')])
        self.h.db.commit()
        with self.assertRaises(test_hub.hub.HubError):
            self.h.edit_chat_message({'chat_id': self.cid, 'message_id': expired,
                                      'text': 'replacement', 'request_id': 'expired-edit-001'})
        history = self.h.history(self.cid)
        self.assertEqual(history['active_version'], original)
        self.assertEqual(len(history['versions']), 1)
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM edit_requests WHERE id=?', ('expired-edit-001',)).fetchone())

    def test_new_chats_title_rename_delete_and_separate_sessions(self):
        self.cookie = self.login()
        status, _, raw = self.api('/api/chats/new', 'POST', {'agent_id': self.aid})
        self.assertEqual(status, 200)
        cid = json.loads(raw)['chat_id']
        self.assertEqual(self.h.chat(cid)['name'], 'New chat')
        first = self.send(cid, 'Plan the orchard')
        self.done(first['job_id'])
        self.assertEqual(self.h.chat(cid)['name'], 'Plan the orchard')
        self.assertIn(cid, [c['id'] for c in self.h.state()['chats']])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM sessions WHERE chat_id=?', (cid,)).fetchone()[0], 1)
        self.assertEqual(self.api('/api/chats/rename', 'POST', {'chat_id': cid, 'name': 'Orchard'})[0], 200)
        self.assertEqual(self.h.chat(cid)['name'], 'Orchard')
        self.assertEqual(self.api('/api/chats/delete', 'POST', {'chat_id': cid})[0], 200)
        self.assertEqual(self.api('/api/chat?id=' + cid)[0], 404)
        self.assertEqual(json.loads(self.api('/api/chats/delete', 'POST', {'chat_id': self.cid})[2])['reset'], True)
        self.assertEqual(self.h.history(self.cid)['messages'], [])

    def test_default_delete_resets_versions_and_request_bookkeeping(self):
        self.cookie = self.login()
        first = self.send(text='first')
        self.done(first['job_id'])
        edited = self.h.edit_chat_message({'chat_id': self.cid, 'message_id': first['message_id'],
                                           'text': 'edited first', 'request_id': 'reset-edit-0001'})
        self.done(edited['job_id'])
        self.h.product_action({'action': 'pin', 'chat_id': self.cid})
        self.h.product_action({'action': 'continue', 'chat_id': self.cid})
        with self.h.lock:
            self.h._put_setting('quick_start_chat', self.cid)
            self.h.db.commit()
        status, _, raw = self.api('/api/chats/delete', 'POST', {'chat_id': self.cid})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)['reset'])
        history = self.h.history(self.cid)
        self.assertEqual(history['messages'], [])
        self.assertEqual(len(history['versions']), 1)
        self.assertEqual(self.h.chat(self.cid)['name'], self.h.agents()[self.aid]['name'])
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM edit_requests WHERE chat_id=?', (self.cid,)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM requests WHERE id=?', ('reset-edit-0001',)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM sessions WHERE chat_id=?', (self.cid,)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM jobs WHERE chat_id=?', (self.cid,)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM chat_preferences WHERE chat_id=?', (self.cid,)).fetchone())
        self.assertIsNone(self.h._setting('last_chat'))
        self.assertIsNone(self.h._setting('quick_start_chat'))
        next_turn = self.send(text='fresh')
        self.done(next_turn['job_id'])
        self.assertEqual([m['text'] for m in self.h.history(self.cid)['messages'] if m['role'] == 'user'], ['fresh'])

    def test_delete_edited_new_chat_removes_edit_request(self):
        cid = self.h.new_direct_chat({'agent_id': self.aid})['chat_id']
        original = self.send(cid, 'draft')
        self.done(original['job_id'])
        edit = self.h.edit_chat_message({'chat_id': cid, 'message_id': original['message_id'],
                                         'text': 'revised', 'request_id': 'deleted-edit-001'})
        self.done(edit['job_id'])
        result = self.h.delete_direct_chat({'chat_id': cid})
        self.assertFalse(result['reset'])
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM edit_requests WHERE id=?', ('deleted-edit-001',)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM requests WHERE id=?', ('deleted-edit-001',)).fetchone())
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM chats WHERE id=?', (cid,)).fetchone())

    def test_edit_keeps_old_branch_and_replays_only_active_prefix(self):
        self.responses(self.aid, [{'result': 'First reply'}, {'result': 'Second reply'},
                                  {'result': 'Edited reply'}, {'result': 'Original continuation'}])
        first = self.send(text='first request')
        self.done(first['job_id'])
        second = self.send(text='old second request')
        self.done(second['job_id'])
        original = self.h.history(self.cid)
        original_version = original['active_version']
        self.assertEqual(len(original['messages']), 4)
        edited = self.h.edit_chat_message({'chat_id': self.cid, 'message_id': second['message_id'],
                                           'text': 'new second request', 'request_id': 'edit-request-0001'})
        self.done(edited['job_id'])
        active = self.h.history(self.cid)
        self.assertEqual([m['text'] for m in active['messages'] if m['role'] == 'user'],
                         ['first request', 'new second request'])
        self.assertEqual(len(active['versions']), 2)
        self.assertNotEqual(active['active_version'], original_version)
        edited_call = self.calls()[-1]['argv']
        self.assertIn('First reply', edited_call[edited_call.index('-p') + 1])
        self.assertNotIn('old second request', edited_call[edited_call.index('-p') + 1])
        self.assertEqual(self.h.search_messages({'q': ['old second request']})['results'], [])
        duplicate = self.h.edit_chat_message({'chat_id': self.cid, 'message_id': second['message_id'],
                                              'text': 'new second request', 'request_id': 'edit-request-0001'})
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.h.history(self.cid)['versions']), 2)
        switched = self.h.switch_chat_version({'chat_id': self.cid, 'version_id': original_version})
        self.assertEqual(switched['active_version'], original_version)
        self.assertIn('old second request', [m['text'] for m in switched['messages']])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM sessions WHERE chat_id=?', (self.cid,)).fetchone()[0], 0)
        continuation = self.send(text='continue original')
        self.done(continuation['job_id'])
        prompt = self.calls()[-1]['argv'][self.calls()[-1]['argv'].index('-p') + 1]
        self.assertIn('old second request', prompt)
        self.assertNotIn('new second request', prompt)

    def test_reject_cross_chat_inactive_and_busy_edits(self):
        first = self.send(text='hello')
        self.done(first['job_id'])
        other = self.h.new_direct_chat({'agent_id': self.aid})['chat_id']
        with self.assertRaises(test_hub.hub.HubError):
            self.h.edit_chat_message({'chat_id': other, 'message_id': first['message_id'],
                                      'text': 'bad', 'request_id': 'cross-chat-001'})
        self.responses(self.aid, [{'sleep': .3, 'result': 'slow'}])
        pending = self.send(text='still working')
        with self.assertRaises(test_hub.hub.HubError) as got:
            self.h.edit_chat_message({'chat_id': self.cid, 'message_id': first['message_id'],
                                      'text': 'bad', 'request_id': 'busy-edit-0001'})
        self.assertEqual(got.exception.status, 409)
        self.done(pending['job_id'])

    def test_stream_delta_has_reply_metadata_and_partial_flag(self):
        self.responses(self.aid, [{'stream': ['one ', 'two'], 'stream_delay': .05}])
        import queue
        events = queue.Queue()
        with self.h.lock:
            self.h.subscribers.add(events)
        sent = self.send(text='stream here')
        self.done(sent['job_id'])
        observed = []
        while not events.empty(): observed.append(events.get_nowait())
        delta = next(event for event in observed if event['kind'] == 'delta')
        self.assertEqual(delta['reply_to'], sent['message_id'])
        self.assertIn('best_fit', delta)
        self.assertIn('routing_kind', delta)
        self.assertIn('independent', delta)
        self.assertIn('--include-partial-messages', self.calls()[-1]['argv'])

    def test_handoff_delta_quotes_the_previous_assistant_message(self):
        import queue
        group = self.h.group({'name': 'Pair', 'agents': ['assistant', 'researcher']})['chat']['id']
        self.responses('assistant', [{'result': 'Starting.\n@@handoff researcher: Check this.'}])
        self.responses('researcher', [{'stream': ['Checked.'], 'result': 'Checked.'}])
        events = queue.Queue()
        with self.h.lock:
            self.h.subscribers.add(events)
        sent = self.send(group, '@assistant Start')
        self.done(sent['job_id'])
        history = self.h.history(group)['messages']
        assistant = next(m for m in history if m['role'] == 'assistant' and m['agent_id'] == 'assistant')
        observed = []
        while not events.empty(): observed.append(events.get_nowait())
        researcher_delta = next(event for event in observed if event['kind'] == 'delta' and event['agent_id'] == 'researcher')
        self.assertEqual(researcher_delta['reply_to'], assistant['id'])
        self.assertEqual(researcher_delta['reply_parent']['id'], assistant['id'])
        self.assertEqual(researcher_delta['reply_parent']['role'], 'assistant')
        self.assertEqual(researcher_delta['reply_parent']['agent_id'], 'assistant')
        self.assertEqual(researcher_delta['reply_parent']['text'], 'Starting.')
        self.assertFalse(researcher_delta['best_fit'])
        self.assertIsNone(researcher_delta['routing_kind'])

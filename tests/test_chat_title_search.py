"""Chat title, edit, search, and explicit-name routing regressions."""
import unittest
from unittest import mock

import test_hub
from hub_chat_polish import directed_member, title_from_message


class ChatTitleSearch(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def send(self, cid, text):
        self.reqnum += 1
        with mock.patch.object(self.h, 'enqueue'):
            result = self.h.send({'chat_id': cid, 'text': text,
                                  'request_id': 'title-search-%04d' % self.reqnum})
        self.h.db.execute("UPDATE jobs SET status='done' WHERE chat_id=?", (cid,))
        self.h.db.commit()
        return result

    def edit(self, cid, mid, text, rid):
        with mock.patch.object(self.h, 'enqueue'):
            result = self.h.edit_chat_message({'chat_id': cid, 'message_id': mid,
                                               'text': text, 'request_id': rid})
        self.h.db.execute("UPDATE jobs SET status='done' WHERE chat_id=?", (cid,))
        self.h.db.commit()
        return result

    def test_exact_title_search_normalizes_case_whitespace_and_finds_empty_chat(self):
        cid = self.h.new_direct_chat({'agent_id': self.aid})['chat_id']
        self.h.rename_direct_chat({'chat_id': cid, 'name': 'Sea  poems'})
        for query in ('Sea poems', 'SEA\tPOEMS', ' sea\n poems ', 'sea'):
            results = self.h.search_messages({'q': [query]})['results']
            match = next(item for item in results if item['chat_id'] == cid)
            self.assertEqual(match['chat_name'], 'Sea  poems')
            self.assertIsNone(match['message_id'])
        self.h.archive({'kind': 'agent', 'id': self.aid})
        self.assertFalse(any(item['chat_id'] == cid for item in self.h.search_messages({'q': ['Sea poems']})['results']))

    def test_message_search_normalizes_multiword_spacing(self):
        self.send(self.cid, 'A separate title')
        self.h.add_message(self.cid, self.aid, 'assistant', 'The sea\n  poems are ready.')
        self.h.db.commit()
        results = self.h.search_messages({'q': ['SEA\tPOEMS']})['results']
        self.assertEqual(results[0]['text'], 'The sea\n  poems are ready.')

    def test_edit_first_turn_refreshes_auto_title_and_version_anchor(self):
        first = self.send(self.cid, 'Original title')
        second = self.send(self.cid, 'Later question')
        original = self.h.history(self.cid)['active_version']
        later = self.edit(self.cid, second['message_id'], 'Later correction', 'later-edit-title')
        self.assertEqual(self.h.chat(self.cid)['name'], 'Original title')
        latest = self.h.history(self.cid)
        self.assertEqual(next(v for v in latest['versions'] if v['active'])['message_id'], later['message_id'])
        changed = self.edit(self.cid, first['message_id'], 'Revised title....', 'first-edit-title')
        self.assertEqual(self.h.chat(self.cid)['name'], 'Revised title…')
        self.assertEqual(next(v for v in self.h.history(self.cid)['versions'] if v['active'])['message_id'], changed['message_id'])
        restored = self.h.switch_chat_version({'chat_id': self.cid, 'version_id': original})
        self.assertEqual(self.h.chat(self.cid)['name'], 'Original title')
        self.assertEqual(next(v for v in restored['versions'] if v['active'])['message_id'], first['message_id'])

    def test_edit_preserves_manual_title(self):
        first = self.send(self.cid, 'Original request')
        self.h.rename_direct_chat({'chat_id': self.cid, 'name': 'My chosen name'})
        self.edit(self.cid, first['message_id'], 'Revised request', 'manual-edit-title')
        self.assertEqual(self.h.chat(self.cid)['name'], 'My chosen name')

    def test_explicit_comma_name_and_mention_use_directed_routing(self):
        group = self.h.group({'name': 'Pair', 'agents': ['assistant', 'researcher']})['chat']['id']
        self.h.edit_agent({'id': 'researcher', 'name': 'Ben'})
        for text in ('Ben, explain it', 'ben: explain it', '@researcher explain it'):
            result = self.send(group, text)
            self.assertEqual(result['routing'], {'kind': 'directed', 'agent_id': 'researcher'})
            job = self.h.db.execute('SELECT best_fit,routing_kind FROM jobs WHERE id=?', (result['job_id'],)).fetchone()
            self.assertFalse(job['best_fit'])
            self.assertEqual(job['routing_kind'], 'directed')
        self.assertIsNone(directed_member('Actually, explain it', ['researcher'], self.h.agents()))

    def test_auto_title_uses_one_ellipsis(self):
        self.assertEqual(title_from_message('Sea poems....'), 'Sea poems…')
        self.assertEqual(title_from_message('Sea poems.'), 'Sea poems.')
        self.assertEqual(title_from_message('Version 1.2'), 'Version 1.2')
        self.h.db.execute('UPDATE chats SET name=? WHERE id=?', ('Old title....', self.cid))
        self.h._put_setting('chat_title_mode:' + self.cid, 'auto')
        self.h.db.commit()
        self.h.state()
        self.assertEqual(self.h.chat(self.cid)['name'], 'Old title…')

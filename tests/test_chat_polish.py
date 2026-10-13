"""Conversation polish regressions with the local fake engine."""
import json
import unittest
from unittest import mock

import hub
import test_hub
from hub_chat_polish import directed_member, title_from_message


class ChatPolish(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    done = test_hub.HubCase.done
    responses = test_hub.HubCase.responses

    def send(self, cid, text, **extra):
        self.reqnum += 1
        return self.h.send({'chat_id': cid, 'text': text,
                            'request_id': 'chat-polish-%04d' % self.reqnum, **extra})

    def test_default_direct_titles_backfill_and_manual_names(self):
        self.assertEqual(title_from_message('x' * 80), 'Long request')
        self.assertEqual(title_from_message(''), 'Attachment')
        self.assertEqual(title_from_message('x' * 80 + ' useful details about budgeting'), 'useful details about budgeting')
        cid = self.cid
        with mock.patch.object(self.h, 'enqueue'):
            self.send(cid, 'Please organize the first project with a detailed plan for next week')
        self.h.db.execute("UPDATE jobs SET status='done' WHERE chat_id=?", (cid,))
        self.h.db.commit()
        self.assertEqual(self.h.chat(cid)['name'], 'Please organize the first project with a detailed plan for')
        self.h.edit_agent({'id': self.aid, 'name': 'Renamed Assistant'})
        self.assertEqual(self.h.chat(cid)['name'], 'Please organize the first project with a detailed plan for')
        other = self.h.new_direct_chat({'agent_id': self.aid})['chat_id']
        self.h.rename_direct_chat({'chat_id': other, 'name': 'My pinned conversation'})
        with mock.patch.object(self.h, 'enqueue'):
            self.send(other, 'A new first message that should not replace my name')
        self.assertEqual(self.h.chat(other)['name'], 'My pinned conversation')
        legacy = self.h.new_direct_chat({'agent_id': self.aid})['chat_id']
        with self.h.lock:
            self.h.add_message(legacy, self.aid, 'user', 'Investigate the old default conversation title')
            self.h.db.commit()
        self.assertEqual(self.h.state()['chats'][next(i for i, c in enumerate(self.h.state()['chats']) if c['id'] == legacy)]['name'],
                         'Investigate the old default conversation title')

    def test_directed_group_member_and_unknown_name(self):
        cid = self.h.group({'name': 'Pair', 'agents': ['assistant', 'researcher']})['chat']['id']
        self.h.edit_agent({'id': 'researcher', 'name': 'Ada'} )
        with mock.patch.object(self.h, 'enqueue'):
            directed = self.send(cid, 'aDa: Explain this in one line')
            explicit = self.send(cid, 'Explain this too', agent_id='researcher')
            mention = self.send(cid, '@assistant Explain the third case', agent_id='researcher')
            named = self.send(cid, 'Ada: Explain the fourth case', agent_id='assistant')
        for sent, expected in ((directed, 'researcher'), (explicit, 'researcher'), (mention, 'assistant'), (named, 'researcher')):
            self.assertEqual(self.h.db.execute('SELECT agent_id FROM jobs WHERE id=?', (sent['job_id'],)).fetchone()[0], expected)
        with mock.patch('hub.cli_choice', return_value='assistant'), mock.patch.object(self.h, 'enqueue'):
            ordinary = self.send(cid, 'Question: explain fractions')
        self.assertIsNotNone(ordinary['job_id'])
        self.assertEqual(directed_member('Ada: do it', ['one', 'two'],
                         {'one': {'name': 'Ada'}, 'two': {'name': 'ADA'}}),
                         ('error', 'Ambiguous group member.'))
        with self.assertRaises(hub.HubError):
            self.send(cid, 'Do work', agent_id='guide')

    def test_self_handoff_explains_skip_without_second_turn(self):
        cid = self.h.group({'name': 'Pair', 'agents': ['assistant', 'researcher']})['chat']['id']
        self.responses('assistant', [{'result': 'Here is the answer.\n@@handoff assistant: Continue it.'}])
        sent = self.send(cid, '@assistant Do the task')
        self.done(sent['job_id'])
        history = self.h.history(cid)['messages']
        self.assertTrue(any('Handoff skipped:' in m['text'] for m in history))
        self.assertEqual(len([m for m in history if m['role'] == 'assistant']), 1)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM handoff_chains').fetchone()[0], 0)

    def test_reaction_replaces_old_and_cancels_pending_unsent_turn(self):
        mid = self.h.add_message(self.cid, self.aid, 'assistant', 'Would you like me to check this?')
        self.h.db.commit()
        first = self.h.react({'message_id': mid, 'emoji': '❓', 'request_id': 'react-first-001'})
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (first['job_id'],)).fetchone()[0], 'queued')
        second = self.h.react({'message_id': mid, 'emoji': '❤️', 'request_id': 'react-second-01'})
        self.assertEqual(second['reactions'], ['❤️'])
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (first['job_id'],)).fetchone()[0], 'stopped')
        self.assertEqual(self.h.react({'message_id': mid, 'emoji': '❤️', 'request_id': 'react-second-01'}), second)
        self.h.db.execute('INSERT INTO decisions VALUES(?,?,?)', (mid, 0, 'Approve'))
        self.h.db.commit()
        third = self.h.react({'message_id': mid, 'emoji': '👍', 'request_id': 'react-third-001'})
        self.assertEqual(third['reactions'], ['👍'])
        self.assertIsNone(third['job_id'])
        self.assertEqual(self.h.db.execute('SELECT action FROM decisions WHERE message_id=?', (mid,)).fetchone()[0], 'Approve')


if __name__ == '__main__':
    unittest.main()

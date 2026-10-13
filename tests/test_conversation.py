"""PASS8 conversation behavior using isolated fake CLI responses."""
import json
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

import hub
from hub_conversation import valid_emoji, cli_choice
from tests import test_hub as fixture


class Conversation(unittest.TestCase):
    setUp = fixture.HubCase.setUp
    send = fixture.HubCase.send
    done = fixture.HubCase.done
    calls = fixture.HubCase.calls
    responses = fixture.HubCase.responses

    def group(self):
        clients = self.h.create_agent({'name': 'Clients', 'role': 'Handle client delivery and inbox.'})['agent']['id']
        builder = self.h.create_agent({'name': 'Builder', 'role': 'Write code and build software.'})['agent']['id']
        return self.h.group({'name': 'Pair', 'agents': [clients, builder], 'emoji': '👥'})['chat']['id']

    def test_best_fit_and_quote_routing_and_attribution(self):
        cid = self.group()
        first = self.send(cid, 'Please handle a client delivery')
        self.assertEqual(first['routing'], {'kind': 'best_fit', 'agent_id': 'clients'})
        self.done(first['job_id'])
        messages = self.h.history(cid)['messages']
        answer = next(m for m in messages if m['role'] == 'assistant')
        self.assertTrue(answer['best_fit'])
        self.assertEqual(answer['best_fit_agent_name'], 'Clients')
        second = self.send(cid, 'Reply here', reply_to=[answer['id']])
        self.done(second['job_id'])
        self.assertEqual(self.h.history(cid)['messages'][-2]['reply_to'], [answer['id']])
        self.assertIn('Replying to Clients (', self.calls('clients')[-1]['argv'][1])

    def test_multiple_quoted_agents_get_own_turns(self):
        cid = self.group()
        sent = self.send(cid, '@all status')
        for jid in sent['job_ids']: self.done(jid)
        answers = [m for m in self.h.history(cid)['messages'] if m['role'] == 'assistant']
        self.assertTrue(all(m['independent'] for m in answers))
        sent = self.send(cid, 'Please clarify both', reply_to=[m['id'] for m in answers])
        self.assertEqual(len(sent['job_ids']), 2)
        for jid in sent['job_ids']: self.done(jid)
        for answer in answers:
            args = self.calls(answer['agent_id'])[-1]['argv']
            prompt = args[args.index('-p') + 1]
            self.assertIn('(context only): ' + answer['text'], prompt)
            self.assertIn('Focus especially on your own quoted message above.', prompt)
            self.assertNotRegex(prompt, r'Focus[^\n]*quoted messages?:\s*\d+')
            system = args[args.index('--append-system-prompt') + 1]
            self.assertIn('Use Markdown when helpful.', system)
            self.assertNotIn('Reply in plain text.', system)
        with self.assertRaises(hub.HubError):
            self.send(cid, 'bad quote', reply_to=[999999])
        with self.assertRaises(hub.HubError):
            self.send(cid, 'too many', reply_to=list(range(6)))

    def test_classifier_fallback_first_member(self):
        cid = self.group()
        with mock.patch('hub.cli_choice', return_value=None) as classify:
            sent = self.send(cid, 'What now?')
        classify.assert_called_once()
        self.assertEqual(sent['routing']['agent_id'], 'clients')
        self.done(sent['job_id'])

    def test_ambiguous_question_prefers_last_addressed_job(self):
        cid = self.group()
        first = self.send(cid, '@builder hello')
        self.done(first['job_id'])
        with mock.patch('hub.cli_choice', return_value=None) as classify:
            second = self.send(cid, 'What now?')
        classify.assert_called_once()
        self.assertEqual(second['routing']['agent_id'], 'builder')
        self.assertEqual(second['routing']['kind'], 'tie')
        self.done(second['job_id'])

    def test_classifier_deadline_and_exact_reply(self):
        with mock.patch.object(self.h, 'isolation_flags', return_value=['--safe-mode']), mock.patch('hub_conversation.run_bounded', side_effect=subprocess.TimeoutExpired(['fake'], 3)) as run:
            self.assertIsNone(cli_choice({'default_engine': 'claude', 'claude_bin': 'fake'}, ['clients', 'builder'], 'status', hub=self.h))
        self.assertEqual(run.call_args.kwargs['timeout'], 15)
        output = subprocess.CompletedProcess(['fake'], 0, json.dumps({'result': 'builder'}), '')
        with mock.patch.object(self.h, 'isolation_flags', return_value=['--safe-mode']), mock.patch('hub_conversation.run_bounded', return_value=output):
            self.assertEqual(cli_choice({'default_engine': 'claude', 'claude_bin': 'fake'}, ['clients', 'builder'], 'status', hub=self.h), 'builder')
        output.stdout = json.dumps({'result': 'builder and clients'})
        with mock.patch.object(self.h, 'isolation_flags', return_value=['--safe-mode']), mock.patch('hub_conversation.run_bounded', return_value=output):
            self.assertIsNone(cli_choice({'default_engine': 'claude', 'claude_bin': 'fake'}, ['clients', 'builder'], 'status', hub=self.h))

    def test_configured_quick_model_and_titles_in_classifier_question(self):
        output = subprocess.CompletedProcess(['fake'], 0, json.dumps({'result': 'builder'}), '')
        profiles = {'clients': {'title': 'Client delivery'}, 'builder': {'title': 'Software builder'}}
        with mock.patch.object(self.h, 'isolation_flags', return_value=['--safe-mode']), mock.patch('hub_conversation.run_bounded', return_value=output) as run:
            chosen = cli_choice({'classifier_engine': 'claude', 'classifier_model': 'sonnet', 'claude_bin': 'fake'},
                                ['clients', 'builder'], 'status', profiles, self.h)
        self.assertEqual(chosen, 'builder')
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--model') + 1], 'sonnet')
        self.assertIn('builder (builder: Software builder', args[args.index('-p') + 1])
        self.assertIn('--safe-mode', args)
        self.assertIn('--strict-mcp-config', args)
        self.assertEqual(args[args.index('--tools') + 1], '')

    def test_classifier_codex_fails_closed_without_a_no_tools_mode(self):
        with mock.patch('hub_conversation.run_bounded') as run:
            chosen = cli_choice({'classifier_engine': 'codex', 'codex_bin': 'fake'},
                                ['clients', 'builder'], 'TOKEN=private-value', hub=self.h)
        self.assertIsNone(chosen)
        run.assert_not_called()

    def test_classifier_claude_fails_closed_if_isolation_is_unavailable(self):
        with mock.patch.object(self.h, 'isolation_flags', side_effect=RuntimeError('unsupported')), mock.patch('hub_conversation.run_bounded') as run:
            chosen = cli_choice({'classifier_engine': 'claude', 'claude_bin': 'fake'},
                                ['clients', 'builder'], 'TOKEN=private-value', hub=self.h)
        self.assertIsNone(chosen)
        run.assert_not_called()

    def test_reactions_persist_and_no_reply(self):
        sent = self.send(text='hello')
        self.done(sent['job_id'])
        answer = [m for m in self.h.history(self.cid)['messages'] if m['role'] == 'assistant'][0]
        self.responses(self.aid, [{'result': 'NO_REPLY'}])
        reaction = {'message_id': answer['id'], 'emoji': '❤️', 'request_id': 'reaction-001'}
        result = self.h.react(reaction)
        self.assertTrue(result['active'])
        self.assertEqual(self.h.react(reaction), result)
        self.assertIsNone(result['job_id'])
        self.assertEqual([m['emoji'] for m in self.h.db.execute('SELECT emoji FROM reactions WHERE message_id=?', (answer['id'],))], ['❤️'])
        self.assertEqual(sum(m['role'] == 'assistant' for m in self.h.history(self.cid)['messages']), 1)
        self.assertFalse(self.h.react({'message_id': answer['id'], 'emoji': '❤️'})['active'])
        self.assertFalse(self.h.react({'message_id': answer['id'], 'emoji': '❤️', 'active': False})['active'])

    def test_plain_answer_thumbs_up_and_question_are_quiet_and_toggle(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                                     'To update the file, run the local command. The file has three sections.')
            self.h.db.commit()
        before = self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        for emoji in ('👍', '❓'):
            body = {'message_id': mid, 'emoji': emoji, 'active': True,
                    'request_id': 'quiet-' + str(ord(emoji[0]))}
            result = self.h.react(body)
            self.assertTrue(result['active'])
            self.assertIsNone(result['job_id'])
            self.assertEqual(self.h.react(body), result)
            self.assertIn(emoji, self.h.history(self.cid)['messages'][-1]['reactions'])
            self.assertFalse(self.h.react({'message_id': mid, 'emoji': emoji})['active'])
            self.assertNotIn(emoji, self.h.history(self.cid)['messages'][-1]['reactions'])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0], before)
        self.assertEqual(self.calls(), [])

    def test_quoted_code_and_negative_offers_are_quiet(self):
        examples = ['The example says "I can send the draft."',
                    '```text\nI can delete the file.\n```',
                    '> I can publish the draft.\nThis is a quote.',
                    'I can not send the file.', 'I will never delete the file.',
                    'I cannot send the file.', 'I propose a name for this theorem.']
        with mock.patch.object(self.h, 'enqueue') as enqueue:
            for text in examples:
                with self.subTest(text=text):
                    mid = self.h.add_message(self.cid, self.aid, 'assistant', text)
                    self.h.db.commit()
                    for emoji in ('👍', '❓'):
                        result = self.h.react({'message_id': mid, 'emoji': emoji, 'active': True})
                        self.assertIsNone(result['job_id'])
            enqueue.assert_not_called()

    def test_natural_action_proposal_reactions_still_queue(self):
        with mock.patch('hub.threading.Timer') as timer:
            for text in ('I can draft the reply and send it after your approval.',
                         "I'll draft the reply once you approve.",
                         'I’ll send it after you approve.',
                         'I propose a draft.',
                         'Would you like me to update the file?',
                         'I suggest we create a new workspace.'):
                with self.h.lock:
                    mid = self.h.add_message(self.cid, self.aid, 'assistant', text)
                    self.h.db.commit()
                for emoji in ('👍', '❓'):
                    result = self.h.react({'message_id': mid, 'emoji': emoji})
                    self.assertIsNotNone(result['job_id'], (text, emoji))
        self.assertEqual(timer.call_count, 12)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs WHERE reaction=1').fetchone()[0], 12)

    def test_group_reaction_targets_author_and_removal_cancels_queued_turn(self):
        cid = self.group()
        self.responses('builder', [{'result': 'I can write the code once you approve.'}])
        sent = self.send(cid, '@builder Write code')
        self.done(sent['job_id'])
        answer = [m for m in self.h.history(cid)['messages'] if m['role'] == 'assistant'][0]
        with mock.patch.object(self.h, 'enqueue'):
            reacted = self.h.react({'message_id': answer['id'], 'emoji': '❓'})
            job = self.h.db.execute('SELECT agent_id,status FROM jobs WHERE id=?', (reacted['job_id'],)).fetchone()
            self.assertEqual((job['agent_id'], job['status']), ('builder', 'queued'))
            self.h.react({'message_id': answer['id'], 'emoji': '❓'})
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (reacted['job_id'],)).fetchone()['status'], 'stopped')

    def test_card_reaction_requires_same_decision_guard(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                'CARD: {"title":"Send draft","actions":["Approve","Skip"]}')
            self.h.db.commit()
        preview = self.h.react({'message_id': mid, 'emoji': '👍'})
        self.assertTrue(preview['confirmation_required'])
        self.assertFalse(self.h.db.execute('SELECT 1 FROM decisions WHERE message_id=?', (mid,)).fetchone())
        result = self.h.react({'message_id': mid, 'emoji': '👍', 'confirm': True})
        self.done(result['job_id'])
        self.assertEqual(self.h.db.execute('SELECT action FROM decisions WHERE message_id=?', (mid,)).fetchone()['action'], 'Approve')

    def test_non_decision_card_reaction_always_acknowledges(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                'CARD: {"title":"Review this","actions":["Go","Hold"]}')
            self.h.db.commit()
        self.responses(self.aid, [{'result': ''}])
        sent = self.h.react({'message_id': mid, 'emoji': '❓', 'active': True, 'request_id': 'feedback-001'})
        self.h._release_reaction(self.aid, sent['job_id'])
        self.done(sent['job_id'])
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (sent['job_id'],)).fetchone()['status'], 'done')
        self.assertTrue(any(m['role'] == 'assistant' and m['reply_to'] == mid and m['text'] for m in self.h.history(self.cid)['messages']))

    def test_emoji_validation_and_edit(self):
        self.assertTrue(valid_emoji('👩‍💻'))
        self.assertTrue(valid_emoji('🇺🇸'))
        self.assertFalse(valid_emoji('😀😀'))
        self.assertFalse(valid_emoji('hello'))
        with self.assertRaises(hub.HubError):
            self.h.create_agent({'name': 'Bad emoji', 'role': 'A role', 'emoji': '😀😀'})
        self.assertEqual(self.h.edit_agent({'id': self.aid, 'emoji': '🧪'})['agent']['emoji'], '🧪')
        cid = self.group()
        self.assertEqual(self.h.rename_group({'id': cid, 'name': 'Pair', 'emoji': '🧩'})['chat']['emoji'], '🧩')

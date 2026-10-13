"""Secret screening at every downloadable export boundary."""
import io
import json
import unittest
import zipfile

import hub_export
import test_hub


class ExportRedaction(unittest.TestCase):
    WARNING = "Exports include your chat text. Review before sharing — we redact obvious secrets but can't catch everything."

    setUp = test_hub.HubCase.setUp

    def test_chat_formats_screen_message_card_and_metadata(self):
        secret = 'A' * 32 + '7Q'
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                'TOKEN=example-value\nBearer shortbearer\n' + secret +
                '\nCARD: {"title":"PASSWORD=card-value","text":"SECRET=card-text","actions":["Review"]}',
                uploads=['/tmp/KEY=attachment-value.txt'])
            cards = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])
            self.assertEqual(len(cards), 1)
            cards[0]['_handoff'] = {'task': 'TOKEN=handoff-value', 'api_key': 'nested-value'}
            self.h.db.execute('UPDATE messages SET cards=? WHERE id=?', (json.dumps(cards), mid))
            self.h.db.commit()
        for payload in (hub_export.markdown_chat(self.h, self.cid), hub_export.json_chat(self.h, self.cid)):
            text = payload.decode()
            for value in ('example-value', 'shortbearer', secret, 'card-value', 'card-text', 'attachment-value',
                          'handoff-value', 'nested-value'):
                self.assertNotIn(value, text)
            self.assertIn('[redacted]', text)
            self.assertIn('redaction', text.lower())

    def test_full_archive_screens_routines_agent_metadata_and_instruction_files(self):
        self.h.create_routine({'agent_id': self.aid, 'name': 'Check',
            'prompt': 'PASSWORD=scheduled-value', 'trigger': 'interval', 'minutes': 10})
        (self.root / 'agents' / 'assistant' / 'NOTES.md').write_text('TOKEN=instruction-value\n')
        (self.root / 'agents' / 'assistant' / 'CLAUDE.md').write_text('-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----')
        with zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h))) as archive:
            names = archive.namelist()
            self.assertIn('agents/assistant/NOTES.md', names)
            self.assertIn('agents/assistant/CLAUDE.md', names)
            body = b'\n'.join(archive.read(name) for name in names).decode()
            self.assertNotIn('scheduled-value', body)
            self.assertNotIn('instruction-value', body)
            readme = archive.read('README.md').decode()
            self.assertIn(self.WARNING, readme)
            self.assertIn('Redactions:', readme)
            self.assertIn('assignment: 2', readme)
            self.assertIn('[redacted]', archive.read('agents/assistant/NOTES.md').decode())
            self.assertIn('[redacted]', archive.read('agents/assistant/CLAUDE.md').decode())
            self.assertIn('[redacted]', archive.read('schedules.json').decode())

    def test_secret_forms_and_fail_closed_value(self):
        cases = ('KEY=abc', 'TOKEN: abc', 'client_secret=abc', 'PASSWORD=abc',
                 '"TOKEN": "value with spaces"', 'apiKey: "mixed case value"',
                 'My password is hunter2', 'my pin is 1234', 'api key: abc123',
                 'password is "two words with spaces"', "my PIN is 'four digit pin'",
                 'TOKEN="escaped \\" quote"', 'TOKEN="unterminated secret and more',
                 'Authorization: Bearer abc', '-----BEGIN PRIVATE KEY-----\na\n-----END PRIVATE KEY-----',
                 'X' * 32, '!@#$%^&*()_+-=[]{}<>/?|~!' * 2)
        for case in cases:
            counts = {}
            self.assertIn('[redacted]', hub_export._redact_text(case, counts), case)
            self.assertGreater(sum(counts.values()), 0)
        for case in ('My password is hunter2', 'my pin is 1234', 'api key: abc123',
                     'password is "two words with spaces"'):
            self.assertNotRegex(hub_export._redact_text(case, {}), r'(?i)(?:hunter2|1234|abc123|two words with spaces)')

    def test_prose_secrets_are_redacted_from_chat_exports(self):
        with self.h.lock:
            self.h.add_message(self.cid, self.aid, 'user',
                'My password is hunter2; my pin is 1234; api key: "two words hidden"')
        for payload in (hub_export.markdown_chat(self.h, self.cid), hub_export.json_chat(self.h, self.cid)):
            text = payload.decode()
            for secret in ('hunter2', '1234', 'two words hidden'):
                self.assertNotIn(secret, text)
            self.assertGreater(text.count('[redacted]'), 2)
        with self.assertRaises(TypeError):
            hub_export._redact_tree({'bad': object()}, {})
        counts = {}
        self.assertEqual(hub_export._redact_tree({'api_key': {'value': 'short-secret'}}, counts),
                         {'api_key': '[redacted]'})
        self.assertEqual(counts['sensitive_field'], 1)
        self.assertEqual(hub_export._redact_text('a' * 20000 + 'SECRET', {}), '[redacted]')


if __name__ == '__main__': unittest.main()

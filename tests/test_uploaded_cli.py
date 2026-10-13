"""Uploaded-file CLI access with local fake engines only."""
import json
from pathlib import Path
import unittest
from urllib.parse import quote

import hub
import test_hub
from test_engines import FAKE_CODEX


class UploadedCLICase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request

    def upload(self, name, data):
        status, _, body = self.api('/api/upload?name=' + quote(name), 'POST', data,
                                   raw=True, headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_claude_uploaded_image_and_file_new_and_resumed(self):
        self.cookie = self.login()
        image = self.upload('photo.png', b'png-bytes')
        document = self.upload('notes.txt', b'notes-bytes')
        pdf = self.upload('report.pdf', b'%PDF-1.7 claude-pdf-bytes')
        self.assertEqual((image['name'], image['size']), ('photo.png', 9))
        self.assertEqual((document['name'], document['size']), ('notes.txt', 11))
        for label in ('first', 'second'):
            self.done(self.send(text=label, uploads=[image['path'], document['path'], pdf['path']])['job_id'])
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            args = call['argv']
            self.assertNotIn('--safe-mode', args)
            self.assertIn('--chrome', args)
            self.assertEqual(args.count('--add-dir'), 1)
            self.assertEqual(args[args.index('--add-dir') + 1], str(self.h.uploads))
            self.assertEqual(call['uploaded_reads'], {
                image['path']: b'png-bytes'.hex(), document['path']: b'notes-bytes'.hex(),
                pdf['path']: b'%PDF-1.7 claude-pdf-bytes'.hex()})
        self.assertNotIn('--resume', calls[0]['argv'])
        self.assertIn('--resume', calls[1]['argv'])
        self.done(self.send(text='without upload')['job_id'])
        self.assertNotIn('--add-dir', self.calls()[-1]['argv'])

    def test_codex_uploaded_images_new_and_resumed(self):
        self.cookie = self.login()
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex'})
        image = self.upload('photo.webp', b'image-bytes')
        second_image = self.upload('another.jpg', b'jpeg-bytes')
        document = self.upload('notes.txt', b'file-bytes')
        pdf = self.upload('report.pdf', b'%PDF-1.7 codex-pdf-bytes')
        for label in ('first', 'second'):
            self.done(self.send('agent:coder', label, uploads=[image['path'], second_image['path'], document['path'], pdf['path']])['job_id'])
        path = self.root / 'agents' / 'coder' / 'fake_codex_calls.jsonl'
        calls = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for call in calls:
            args = call['argv']
            self.assertNotIn('--ignore-user-config', args)
            self.assertNotIn('--ignore-rules', args)
            self.assertEqual(call['home'], str(self.root))
            self.assertEqual(call['codex_home'], str(self.root / 'fake-source-codex-home'))
            self.assertEqual(args.count('--image'), 2)
            self.assertEqual(args[-2], '--', 'variadic images cannot consume the prompt')
            self.assertEqual([args[i + 1] for i, arg in enumerate(args) if arg == '--image'],
                             [image['path'], second_image['path']])
            self.assertNotIn(document['path'], args[:-1])
            self.assertIn(document['path'], args[-1])
            self.assertEqual(call['uploaded_reads'], {
                image['path']: b'image-bytes'.hex(), second_image['path']: b'jpeg-bytes'.hex(),
                document['path']: b'file-bytes'.hex(), pdf['path']: b'%PDF-1.7 codex-pdf-bytes'.hex()})
            self.assertNotIn('--add-dir', args)
        self.assertNotIn('resume', calls[0]['argv'])
        self.assertIn('resume', calls[1]['argv'])

    def test_invalidated_upload_is_excluded_at_launch(self):
        self.cookie = self.login()
        image = self.upload('photo.png', b'valid')
        self.h.enqueue = lambda aid, jid: None
        job = self.send(text='inspect', uploads=[image['path']])['job_id']
        Path(image['path']).unlink()
        self.h.execute(job)
        self.assertNotIn('--add-dir', self.calls()[-1]['argv'])
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex'})
        replacement = self.upload('replacement.png', b'valid')
        job = self.send('agent:coder', 'inspect', uploads=[replacement['path']])['job_id']
        Path(replacement['path']).unlink()
        self.h.execute(job)
        path = self.root / 'agents' / 'coder' / 'fake_codex_calls.jsonl'
        args = json.loads(path.read_text().splitlines()[-1])['argv']
        self.assertNotIn('--image', args)

    def test_held_job_retry_revalidates_upload(self):
        self.cookie = self.login()
        image = self.upload('photo.gif', b'gif-bytes')
        self.h.held_engines.clear()
        (self.root / 'agents' / 'assistant' / 'fake_responses.json').write_text(json.dumps([
            {'is_error': True, 'result': 'usage limit reached'},
            {'result': 'recovered'},
        ]))
        jid = self.send(text='retry me', uploads=[image['path']])['job_id']
        test_hub.poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'held_limit')
        self.h.retry_job({'job_id': jid})
        self.done(jid)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call['argv'][call['argv'].index('--add-dir') + 1], str(self.h.uploads))
            self.assertEqual(call['uploaded_reads'][image['path']], b'gif-bytes'.hex())

    def test_uploaded_active_content_stays_private_download(self):
        self.cookie = self.login()
        for name, data in (('drawing.svg', b'<svg></svg>'), ('page.html', b'<h1>Hi</h1>')):
            with self.subTest(name=name):
                info = self.upload(name, data)
                self.assertEqual(info['name'], name)
                self.assertEqual(info['size'], len(data))
                status, headers, body = self.api(info['url'])
                self.assertEqual((status, body), (200, data))
                self.assertIn('Content-Type: application/octet-stream', headers)
                self.assertIn('Content-Disposition: attachment;', headers)
                self.assertIn('X-Content-Type-Options: nosniff', headers)
                self.assertIn('Cache-Control: no-store', headers)
                self.assertIn("img-src 'self' blob:;", headers)
                self.assertIn("script-src 'self';", headers)
        del self.cookie
        self.assertEqual(self.api(info['url'])[0], 401)

    def test_image_metadata_is_only_served_to_authenticated_owner(self):
        self.cookie = self.login()
        payload = b'\xff\xd8\xff\xe1Exif\x00\x00private-owner-metadata\xff\xd9'
        image = self.upload('../../owner.jpg', payload)
        self.assertEqual(image['name'], 'owner.jpg')
        self.assertEqual(image['kind'], 'image')
        status, headers, content = self.api(image['url'])
        self.assertEqual((status, content), (200, payload))
        self.assertIn('Cache-Control: no-store', headers)
        self.assertIn('X-Content-Type-Options: nosniff', headers)
        self.assertNotIn('private-owner-metadata', json.dumps(image))
        del self.cookie
        self.assertEqual(self.api(image['url'])[0], 401)
        self.assertEqual(self.api('/data/uploads/' + Path(image['path']).name)[0], 404)


if __name__ == '__main__':
    unittest.main()

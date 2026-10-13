"""Message-bound previews for FILE images in a Pip working folder."""
from pathlib import Path
import unittest
from unittest import mock
from urllib.parse import quote

import hub
import test_hub


class ChatWorkdirMedia(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request
    def _assistant_message(self, cid, aid, text):
        with self.h.lock:
            mid = self.h.add_message(cid, aid, 'assistant', text)
            self.h.db.commit()
        return mid

    def _scoped_url(self, cid, mid, path):
        return ('/api/file?chat_id=' + quote(cid, safe='') + '&message_id=' + str(mid)
                + '&path=' + quote(str(path), safe=''))

    def test_workdir_image_renders_only_for_referencing_message_and_chat(self):
        self.cookie = self.login()
        project = self.root / 'project'; project.mkdir()
        image = project / 'drawing.png'; image.write_bytes(b'fake-png-content')
        self.h.edit_agent({'id': self.aid, 'workdir': str(project)})
        mid = self._assistant_message(self.cid, self.aid, 'Here it is.\nFILE: ' + str(image))
        attachment = self.h.history(self.cid)['messages'][-1]['attachments'][0]
        self.assertEqual(attachment['kind'], 'image')
        self.assertEqual(attachment['url'], self._scoped_url(self.cid, mid, image))
        self.assertEqual(self.api(attachment['url'])[2], b'fake-png-content')
        self.assertEqual(self.api('/api/file?path=' + quote(str(image)))[0], 403)

        other = self.h.create_agent({'name': 'Other', 'role': 'Other work.'})['chat_id']
        other_mid = self._assistant_message(other, 'other', 'FILE: ' + str(image))
        self.assertEqual(self.api(self._scoped_url(other, other_mid, image))[0], 403)
        self.assertEqual(self.api(self._scoped_url(other, mid, image))[0], 403)
        unrelated = project / 'unmentioned.png'; unrelated.write_bytes(b'unmentioned')
        self.assertEqual(self.api(self._scoped_url(self.cid, mid, unrelated))[0], 403)
        replacement = self.root / 'replacement'; replacement.mkdir()
        self.h.edit_agent({'id': self.aid, 'workdir': str(replacement)})
        self.assertEqual(self.api(attachment['url'])[0], 403)

    def test_missing_and_unsafe_images_have_placeholder_and_no_download(self):
        self.cookie = self.login()
        project = self.root / 'project'; project.mkdir()
        self.h.edit_agent({'id': self.aid, 'workdir': str(project)})
        outside = self.root / 'outside.png'; outside.write_bytes(b'outside')
        link = project / 'link.png'; link.symlink_to(outside)
        hidden = project / '.secret.png'; hidden.write_bytes(b'secret')
        for image in (project / 'missing.png', link, hidden, outside):
            with self.subTest(image=image):
                mid = self._assistant_message(self.cid, self.aid, 'FILE: ' + str(image))
                attachment = self.h.history(self.cid)['messages'][-1]['attachments'][0]
                self.assertTrue(attachment['unavailable'])
                self.assertEqual(attachment['kind'], 'unavailable')
                self.assertNotIn('url', attachment)
                self.assertEqual(self.api(self._scoped_url(self.cid, mid, image))[0], 403)

    def test_only_owned_default_agent_folder_can_be_saved_outside_home(self):
        agent_folder = self.root / 'agents' / self.aid
        other = self.root / 'arbitrary'; other.mkdir()
        fake_home = self.root / 'different-home'; fake_home.mkdir()
        with mock.patch('pathlib.Path.home', return_value=fake_home):
            edited = self.h.edit_agent({'id': self.aid, 'workdir': str(agent_folder)})
            self.assertEqual(edited['agent']['workdir'], str(agent_folder))
            for path in (other, self.root / 'agents', self.root / 'agents' / 'researcher'):
                with self.subTest(path=path), self.assertRaises(hub.HubError):
                    self.h.edit_agent({'id': self.aid, 'workdir': str(path)})

    def test_default_folder_file_gets_scoped_url_and_relative_reference_works(self):
        self.cookie = self.login()
        folder = self.root / 'agents' / self.aid
        image = folder / 'result.png'; image.write_bytes(b'result')
        mid = self._assistant_message(self.cid, self.aid, 'FILE: result.png')
        attachment = self.h.history(self.cid)['messages'][-1]['attachments'][0]
        self.assertEqual(attachment['url'], self._scoped_url(self.cid, mid, 'result.png'))
        self.assertEqual(self.api(attachment['url'])[2], b'result')

    def test_midline_file_markers_expose_only_renderable_image_spans(self):
        self.cookie = self.login()
        folder = self.root / 'agents' / self.aid
        image = folder / 'chart.png'; image.write_bytes(b'image')
        text = 'Here is FILE: chart.png and FILE: missing.png; keep the caption.'
        mid = self._assistant_message(self.cid, self.aid, text)
        message = self.h.history(self.cid)['messages'][-1]
        self.assertEqual(message['text'], text)
        attachments = message['attachments']
        self.assertEqual(len(attachments), 2)
        shown = next(item for item in attachments if item['kind'] == 'image')
        missing = next(item for item in attachments if item['kind'] == 'unavailable')
        start, end = shown['file_marker_spans'][0]
        self.assertEqual(text[start:end], 'FILE: chart.png')
        self.assertEqual(self.api(shown['url'])[2], b'image')
        self.assertNotIn('file_marker_spans', missing)
        self.assertEqual(self.api(self._scoped_url(self.cid, mid, 'missing.png'))[0], 403)

    def test_midline_marker_does_not_authorize_unmentioned_image(self):
        self.cookie = self.login()
        folder = self.root / 'agents' / self.aid
        image = folder / 'chart.png'; image.write_bytes(b'image')
        mid = self._assistant_message(self.cid, self.aid, 'See FILE: other.png and chart.png.')
        self.assertEqual(self.api(self._scoped_url(self.cid, mid, image))[0], 403)

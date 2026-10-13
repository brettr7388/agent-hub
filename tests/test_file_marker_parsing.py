"""Inline image markers preserve the standalone download marker contract."""
import unittest

from hub_chat_media import file_references


class FileMarkerParsing(unittest.TestCase):
    def test_standalone_pdf_download_marker_is_preserved(self):
        self.assertEqual(list(file_references('FILE: /tmp/my report.pdf')), [('/tmp/my report.pdf', 0, 24)])

    def test_midline_images_have_exact_nonduplicated_spans(self):
        text = 'Here: FILE: /tmp/my shot.png looks good.\nFILE: /tmp/other.jpg'
        markers = list(file_references(text))
        self.assertEqual([raw for raw, _, _ in markers], ['/tmp/my shot.png', '/tmp/other.jpg'])
        for raw, start, end in markers:
            self.assertEqual(text[start:end], 'FILE: ' + raw)

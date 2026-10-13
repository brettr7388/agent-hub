"""Phone sizing and compact conversation controls CSS contracts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'static/style.css').read_text()


class PhoneCSSContractTests(unittest.TestCase):
    def test_settings_tabs_scroll_in_one_row(self):
        rule = CSS.rsplit('.settings-tabs{', 1)[1].split('}', 1)[0]
        button = CSS.rsplit('.settings-tabs button{', 1)[1].split('}', 1)[0]
        self.assertIn('flex-wrap:nowrap', rule)
        self.assertIn('overflow-x:auto', rule)
        self.assertIn('flex:0 0 auto', button)

    def test_phone_hit_targets_and_star_label_clearance(self):
        self.assertIn('.icon-button,.pin-button,.voice-button,.attach-button,.send-button{width:44px;height:44px;min-width:44px;min-height:44px;padding:0}', CSS)
        self.assertIn('.guide-starters button,.message .card-actions button,.message .card-list>button{min-height:44px}', CSS)
        self.assertIn('.footer-pill,.header-text-button,#chatManageButton,.model-selector,.ask-everyone,.stop-button,.sidebar-tools button,#newChatButton{min-height:44px;min-width:44px}', CSS)
        self.assertIn('.sidebar .nav-wrap>.pin-button{top:2px;right:44px;width:44px;height:44px;transform:none}', CSS)
        self.assertIn('.sidebar .nav-wrap:not(.pip-conversations)>.nav-item{width:calc(100% - 88px)}', CSS)
        self.assertIn('.sidebar .nav-wrap.pip-conversations>.nav-item{width:calc(100% - 44px)}', CSS)
        self.assertIn('.conversation-more{width:44px;min-width:44px;min-height:44px', CSS)

    def test_preview_search_and_inline_version_rules(self):
        self.assertIn('.upload-thumbnail{width:112px;height:72px;object-fit:contain;object-position:center;background:var(--panel2)}', CSS)
        self.assertIn('input[type="search"]::-webkit-search-cancel-button{display:none;-webkit-appearance:none}', CSS)
        self.assertIn('.message-version-control{position:relative;display:flex;align-items:center;justify-content:center', CSS)
        self.assertIn('margin:4px auto 0', CSS)


if __name__ == '__main__':
    unittest.main()

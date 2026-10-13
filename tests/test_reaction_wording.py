from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReactionWordingTests(unittest.TestCase):
    def test_backend_reaction_legend_uses_current_meanings_and_keeps_gates(self):
        source = (ROOT / 'hub.py').read_text()
        match = re.search(r"where \+= '( Reaction legend: [^']+)'", source)
        self.assertIsNotNone(match, 'backend reaction legend should remain present')
        legend = match.group(1)
        for emoji in ('👍', '👎', '❤️', '❓'):
            self.assertIn(emoji, legend)
        for legacy in ('😂', '✅'):
            self.assertNotIn(legacy, legend)
        self.assertIn('draft-only and all approval gates still apply', legend)
        self.assertIn('This approval covers only the reacted message proposal', legend)

    def test_readme_and_help_describe_only_current_quick_reactions(self):
        readme = (ROOT / 'README.md').read_text()
        index = (ROOT / 'static/index.html').read_text()
        readme_copy = next(line for line in readme.splitlines() if line.startswith('Reactions have clear meanings:'))
        help_match = re.search(r'<summary>Messages, groups, and team tasks</summary><p>(.*?)</p>', index)
        self.assertIsNotNone(help_match, 'Help reaction description should remain present')
        help_copy = help_match.group(1)

        for copy in (readme_copy, help_copy):
            for emoji in ('👍', '👎', '❤️', '❓'):
                self.assertIn(emoji, copy)
            for legacy in ('😂', '✅'):
                self.assertNotIn(legacy, copy)
        self.assertIn('send the exact approval or decline to the same Pip', readme_copy)
        self.assertIn('Approve or Don’t sends your answer to that Pip', help_copy)


if __name__ == '__main__':
    unittest.main()

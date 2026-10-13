from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Pass17WordingTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text()

    def test_saved_token_and_recovery_are_explained_at_each_entry_point(self):
        readme = self.read('README.md')
        setup = self.read('SETUP.md')
        index = self.read('static/index.html')
        app = self.read('static/app.js')
        backend = self.read('hub.py')
        self.assertIn('login token shown once', readme)
        self.assertIn('save it for later logins', readme.lower())
        self.assertIn('python3 hub.py --reset-token', readme)
        self.assertIn('login token shown once', setup)
        self.assertIn('python3 hub.py --reset-token', setup)
        self.assertIn('Use the token you saved at first start', index)
        self.assertIn('python3 hub.py --reset-token', index)
        self.assertIn('Use the token you saved at first start', app)
        self.assertIn('python3 hub.py --reset-token', backend)
        self.assertIn('Login token (shown once; save it): ', backend)

    def test_docs_identify_guide_first_run_and_home_folder_limit(self):
        readme = self.read('README.md')
        self.assertIn('![Guide first-run screen](docs/screenshot-welcome.png)', readme)
        self.assertIn('Working folders must be inside your home folder', readme)
        self.assertIn('~/Projects/my-app', readme)

    def test_demo_copy_sets_duration_expectation_before_create_all(self):
        index = self.read('static/index.html')
        app = self.read('static/app.js')
        guide = self.read('hub_guide.py')
        self.assertNotIn('30-second demo', app)
        self.assertIn('Try the Chef and Critic demo', app)
        self.assertIn('This demo uses your signed-in CLI and may take longer than 30 seconds.', app)
        self.assertIn('Create all', app)
        self.assertIn('signed-in CLI and may take longer than 30 seconds', guide)
        self.assertIn('signed-in CLI and may take longer than 30 seconds', index)


if __name__ == '__main__':
    unittest.main()

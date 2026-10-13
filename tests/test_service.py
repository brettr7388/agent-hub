"""Service plans are verified in temporary homes, without installing a job."""
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock

import hub_service


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hub-service-')
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = (base / 'hub').resolve()
        self.home = (base / 'home').resolve()
        self.root.mkdir()
        self.home.mkdir()

    def test_macos_install_is_explicit_and_reversible(self):
        path = self.home / 'Library' / 'LaunchAgents' / (hub_service.LABEL + '.plist')
        self.assertFalse(path.exists())
        result = hub_service.handle_service('install', self.root, platform='darwin', home=self.home,
                                            python='/usr/bin/python3')
        self.assertIn('launchctl bootstrap', result)
        with path.open('rb') as stream:
            plan = plistlib.load(stream)
        self.assertTrue(plan['KeepAlive'])
        self.assertTrue(plan['RunAtLoad'])
        self.assertEqual(plan['WorkingDirectory'], str(self.root))
        self.assertEqual(plan['ProgramArguments'], ['/usr/bin/python3', str(self.root / 'hub.py')])
        self.assertEqual(Path(plan['StandardOutPath']).parent, self.root / 'data')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'data' / 'hub.stdout.log').stat().st_mode & 0o777, 0o600)
        hub_service.handle_service('install', self.root, platform='darwin', home=self.home,
                                   python='/usr/bin/python3')
        result = hub_service.handle_service('uninstall', self.root, platform='darwin', home=self.home)
        self.assertIn('launchctl bootout', result)
        self.assertFalse(path.exists())

    def test_different_existing_job_is_not_overwritten(self):
        path = self.home / 'Library' / 'LaunchAgents' / (hub_service.LABEL + '.plist')
        path.parent.mkdir(parents=True)
        path.write_bytes(plistlib.dumps({'Label': hub_service.LABEL, 'WorkingDirectory': '/another/hub'}))
        with self.assertRaises(RuntimeError):
            hub_service.handle_service('install', self.root, platform='darwin', home=self.home)
        with self.assertRaises(RuntimeError):
            hub_service.handle_service('uninstall', self.root, platform='darwin', home=self.home)
        self.assertTrue(path.exists())

    def test_linux_returns_unit_without_installing(self):
        result = hub_service.handle_service('install', self.root, platform='linux', home=self.home,
                                            python='/usr/bin/python3')
        self.assertIn('Restart=always', result)
        self.assertIn('WorkingDirectory="' + str(self.root) + '"', result)
        self.assertIn('ExecStart="/usr/bin/python3" "' + str(self.root / 'hub.py') + '"', result)
        self.assertFalse((self.home / '.config').exists())
        self.assertIn('disable --now', hub_service.handle_service('uninstall', self.root, platform='linux', home=self.home))

    def test_systemd_rejects_control_characters_in_every_dynamic_value(self):
        with mock.patch.dict(hub_service.os.environ, {'PATH': '/bin\nExecStart=/bin/false'}):
            with self.assertRaises(ValueError): hub_service.systemd_unit(self.root)
        with mock.patch.dict(hub_service.os.environ, {'CODEX_HOME': '/tmp/codex\rRestart=no'}):
            with self.assertRaises(ValueError): hub_service.systemd_unit(self.root)
        with self.assertRaises(ValueError): hub_service.systemd_unit(self.root, python='/bin/python\t--bad')
        path_with_newline = self.root.parent / 'hub\nRestart=no'
        with self.assertRaises(ValueError): hub_service.systemd_unit(path_with_newline)

    def test_systemd_quotes_log_paths_and_environment_assignments(self):
        unit = hub_service.systemd_unit(self.root, python='/bin/a python')
        self.assertIn('StandardOutput=append:"' + str(self.root / 'data' / 'hub.stdout.log') + '"', unit)
        self.assertIn('StandardError=append:"' + str(self.root / 'data' / 'hub.stderr.log') + '"', unit)
        self.assertIn('Environment="PATH=', unit)


if __name__ == '__main__': unittest.main()

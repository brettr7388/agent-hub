"""Explicit, local service setup for Agent Hub. Importing this module has no effects."""

import os
from pathlib import Path
import plistlib
import shlex
import sys
from hub_fs import chmod, ensure_file, mkdir, open_file, unlink


LABEL = 'com.agenthub.hub'
SYSTEMD_UNIT = 'agent-hub.service'


def launch_agent(root, python=None):
    root = Path(root).resolve()
    python = str(python or sys.executable)
    data = root / 'data'
    environment = {'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin')}
    if os.environ.get('CODEX_HOME'):
        environment['CODEX_HOME'] = os.environ['CODEX_HOME']
    return {
        'Label': LABEL,
        'ProgramArguments': [python, str(root / 'hub.py')],
        'WorkingDirectory': str(root),
        'RunAtLoad': True,
        'KeepAlive': True,
        'StandardOutPath': str(data / 'hub.stdout.log'),
        'StandardErrorPath': str(data / 'hub.stderr.log'),
        'EnvironmentVariables': environment,
    }


def systemd_unit(root, python=None):
    root = Path(root).resolve()
    python = str(python or sys.executable)
    def quote_unit(value):
        value = str(value)
        if any(ord(char) < 32 or ord(char) == 127 or 128 <= ord(char) <= 159 for char in value):
            raise ValueError('Systemd unit values cannot contain control characters.')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    environment = 'Environment=' + quote_unit('PATH=' + os.environ.get('PATH', '/usr/local/bin:/usr/bin:/opt/homebrew/bin')) + '\n'
    if os.environ.get('CODEX_HOME'):
        environment += 'Environment=' + quote_unit('CODEX_HOME=' + os.environ['CODEX_HOME']) + '\n'
    return ('[Unit]\nDescription=Agent Hub\nAfter=network.target\n\n'
            '[Service]\nType=simple\nWorkingDirectory=' + quote_unit(root) + '\n'
            'ExecStart=' + quote_unit(python) + ' ' + quote_unit(root / 'hub.py') + '\n' + environment +
            'Restart=always\nRestartSec=5\nStandardOutput=append:' + quote_unit(root / 'data' / 'hub.stdout.log') + '\n'
            'StandardError=append:' + quote_unit(root / 'data' / 'hub.stderr.log') + '\n\n'
            '[Install]\nWantedBy=default.target\n')


def handle_service(action, root, platform=None, home=None, python=None):
    """Install only when explicitly invoked; Linux returns a unit for review."""
    if action not in ('install', 'uninstall'):
        raise ValueError('Service action must be install or uninstall.')
    platform = platform or sys.platform
    root = Path(root).resolve()
    if platform == 'darwin':
        home = Path(home or Path.home()).expanduser()
        path = home / 'Library' / 'LaunchAgents' / (LABEL + '.plist')
        if action == 'uninstall':
            if path.exists():
                with open_file(path, 'rb') as stream:
                    installed = plistlib.load(stream)
                if installed.get('Label') != LABEL or installed.get('WorkingDirectory') != str(root):
                    raise RuntimeError('Existing LaunchAgent belongs to another Agent Hub; it was not removed.')
                unlink(path, approved_names={path.name})
            return 'LaunchAgent removed if present. To stop a loaded job, run: launchctl bootout gui/$(id -u)/' + LABEL
        data = root / 'data'
        mkdir(data, mode=0o700, exist_ok=True)
        chmod(data, 0o700)
        for name in ('hub.stdout.log', 'hub.stderr.log'):
            log = data / name
            ensure_file(log, mode=0o600)
        mkdir(path.parent, parents=True, exist_ok=True)
        payload = plistlib.dumps(launch_agent(root, python))
        if path.exists():
            with open_file(path, 'rb') as stream:
                current = stream.read()
            if current != payload:
                raise RuntimeError('A different Agent Hub LaunchAgent already exists; it was not overwritten.')
        else:
            with open_file(path, 'xb') as stream:
                stream.write(payload)
                os.fchmod(stream.fileno(), 0o600)
        return 'LaunchAgent installed at ' + str(path) + '. To start it, run: launchctl bootstrap gui/$(id -u) ' + shlex.quote(str(path))
    if platform.startswith('linux'):
        if action == 'uninstall':
            return ('If installed, run: systemctl --user disable --now ' + SYSTEMD_UNIT + '; '
                    'then remove ~/.config/systemd/user/' + SYSTEMD_UNIT + ' and run systemctl --user daemon-reload.')
        return ('Review this unit, save it as ~/.config/systemd/user/' + SYSTEMD_UNIT + ', '
                'then run systemctl --user daemon-reload && systemctl --user enable --now ' + SYSTEMD_UNIT + ':\n\n'
                + systemd_unit(root, python))
    raise RuntimeError('Service setup supports macOS LaunchAgents and Linux systemd user units.')

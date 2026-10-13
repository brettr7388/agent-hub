"""Explicit instruction policy for hub-owned agents, without relocating credentials."""
import os
import difflib
import hashlib
import logging
from pathlib import Path
import re
import shutil
import subprocess
from hub_security import allowed_agent_environment, open_validated_file
from hub_process import run_bounded, OutputLimitExceeded
from hub_fs import read_bytes, atomic_write_text, mkdir, listdir, chmod, symlink


CODEX_CONFIG = ('model = "gpt-6-luna"\nproject_doc_max_bytes = 0\nproject_doc_fallback_filenames = []\n'
                'developer_instructions = ""\n[skills]\ninclude_instructions = false\n'
                '[skills.bundled]\nenabled = false\n[features]\n'
                'skip_host_skill_discovery = true\nskill_search = false\n'
                'external_agent_memory_import = false\nplugins = false\n'
                'remote_plugin = false\nplugin_sharing = false\n')


def restore_codex_config(account):
    """Codex owns runtime mutations; Hub owns the next invocation's template."""
    config = account / 'config.toml'
    if config.is_symlink():
        raise RuntimeError('Hub Codex config path is a symlink; inspect data/codex-home-v3/config.toml before retrying.')
    if config.exists():
        previous = read_bytes(config)
        if previous != CODEX_CONFIG.encode('utf-8'):
            # Record exactly which lines changed without leaking config values
            # (a provider token or developer instruction may have been added).
            changes = list(difflib.ndiff(CODEX_CONFIG.splitlines(), previous.decode('utf-8', errors='replace').splitlines()))
            keys = sorted({match.group(1) for line in changes if line[:2] in ('+ ', '- ')
                           for match in [re.match(r'\s*([A-Za-z0-9_.-]+)\s*=', line[2:])] if match})
            added = sum(line.startswith('+ ') for line in changes)
            removed = sum(line.startswith('- ') for line in changes)
            logging.getLogger(__name__).warning(
                'Restoring Hub Codex config.toml after runtime changes: keys=%s; lines added=%d removed=%d; '
                'previous_sha256=%s; template_sha256=%s (values omitted)',
                ','.join(keys) or '<section/comment changes>', added, removed,
                hashlib.sha256(previous).hexdigest(), hashlib.sha256(CODEX_CONFIG.encode('utf-8')).hexdigest())
    # Replace on EVERY invocation, even if bytes match; no half-written config
    # can be observed by another Hub runner. Private mode survives replacement.
    atomic_write_text(config, CODEX_CONFIG)


class IsolationMixin:
    def claude_stream_flags(self, binary):
        """Older CLIs stream full messages but do not accept the partial flag."""
        with self.lock:
            cache = getattr(self, '_claude_partial_support', None)
            if cache is None:
                cache = self._claude_partial_support = {}
            if binary not in cache:
                try:
                    result = run_bounded([binary, '--help'], timeout=5,
                                         env=allowed_agent_environment())
                    cache[binary] = result.returncode == 0 and '--include-partial-messages' in result.stdout
                except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded):
                    cache[binary] = False
            return ['--include-partial-messages'] if cache[binary] else []

    def claude_full_access_flags(self, binary):
        """Print mode needs autonomous permissions for tools outside allow lists."""
        with self.lock:
            if self.config.get('full_access_permission_mode', 'auto') == 'inherit': return []
            cache = getattr(self, '_claude_auto_support', None)
            if cache is None:
                cache = self._claude_auto_support = {}
            if binary not in cache:
                try:
                    result = run_bounded([binary, '--help'], timeout=5,
                                         env=allowed_agent_environment())
                    choices = re.search(r'--permission-mode\b(?:(?!\n\s*--).)*?\bchoices\s*:\s*([^)]*)\)',
                                        result.stdout, re.S)
                    cache[binary] = (result.returncode == 0 and choices is not None and
                                     'auto' in re.findall(r'[A-Za-z][A-Za-z0-9]*', choices.group(1)))
                except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded):
                    cache[binary] = False
            return (['--permission-mode', 'auto'] if cache[binary] else
                    ['--permission-mode', 'acceptEdits', '--allowedTools', 'WebSearch,WebFetch'])

    def require_engine(self, engine, binary):
        if not shutil.which(binary):
            raise RuntimeError(engine.title() + " isn't installed or cannot be found. Open Help → Install an engine, install the CLI, then restart Agent Hub.")
        if getattr(self, 'engine_auth', {}).get(engine) == 'login_required':
            command = 'claude' if engine == 'claude' else 'codex login'
            raise RuntimeError(engine.title() + " isn't signed in. Open Terminal and run: " + command + ', then log in and restart Agent Hub.')

    def rules_policy(self, agent, engine=None):
        # Mode and prompt changes start a fresh session, including older sessions.
        mode = 'private' if agent.get('private_pip') else 'full'
        policy = 'access-v24-browser-' + mode + ('-draft' if agent.get('draft_only') else '')
        if mode == 'full' and not agent.get('draft_only'):
            engine = engine or agent.get('engine', 'claude')
            policy += '-permissions-v27-' + (self.config.get('full_access_permission_mode', 'auto')
                                             if engine == 'claude' else 'workspace-write')
        return policy

    def codex_environment(self):
        """Give an isolated turn an empty Codex account with access to auth only.

        CODEX_HOME is also where Codex discovers its global AGENTS.md. CLI flags
        alone did not prevent that file from reaching a real model turn.
        """
        with self.lock:
            source_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
            source_auth = source_home / 'auth.json'
            if not source_auth.is_file():
                raise RuntimeError('Codex auth.json is unavailable. Sign in with the regular Codex CLI, then retry the isolated turn.')
            # Leave v2 accounts untouched: Codex may have installed system skills
            # there, and their sessions may already contain skill instructions.
            account = self.data / 'codex-home-v3'
            if account.is_symlink():
                raise RuntimeError('Hub Codex account path is a symlink; inspect data/codex-home-v3 before retrying.')
            mkdir(account, mode=0o700, exist_ok=True)
            chmod(account, 0o700)
            # Runtime-owned session/cache files may appear here. Reject anything
            # able to introduce automatic instructions or tools.
            forbidden = {'AGENTS.md', 'AGENTS.override.md', 'skills', '.agents', '.codex', 'rules', 'memories',
                         'memory', 'plugins', 'hooks', 'mcp', 'mcp.json', 'profiles'}
            for entry in listdir(account):
                if entry.name in forbidden or entry.name.lower().startswith('agents.'):
                    raise RuntimeError('Unexpected instruction source in Hub Codex account: ' + entry.name)
            auth = account / 'auth.json'
            # A symlink follows refreshed credentials without a second token copy.
            if auth.is_symlink():
                if auth.resolve() != source_auth.resolve():
                    raise RuntimeError('Hub Codex auth link changed; inspect data/codex-home-v3/auth.json before retrying.')
            elif auth.exists():
                raise RuntimeError('Hub Codex auth path is occupied; inspect data/codex-home-v3/auth.json before retrying.')
            else:
                symlink(auth, source_auth.resolve())
            restore_codex_config(account)
            env = allowed_agent_environment()
            env['CODEX_HOME'] = str(account)
            # skip_host_skill_discovery does not suppress ~/.agents/skills in
            # CLI 0.160.0. Keep Codex's OS-home skill search away from user files.
            # Authentication still uses the auth.json symlink above.
            env['HOME'] = str(account)
            return env

    def isolation_flags(self, engine, binary):
        with self.lock:
            cache = getattr(self, '_isolation_help', None)
            if cache is None:
                cache = self._isolation_help = {}
        key = (engine, binary)
        required = ('--safe-mode',) if engine == 'claude' else ('--ignore-user-config', '--ignore-rules')
        with self.lock:
            if key not in cache:
                try:
                    args = [binary, '--help'] if engine == 'claude' else [binary, 'exec', '--help']
                    result = run_bounded(args, timeout=5, env=allowed_agent_environment())
                    cache[key] = result.returncode == 0 and all(flag in result.stdout for flag in required)
                    if engine == 'codex' and cache[key]:
                        resume = run_bounded([binary, 'exec', 'resume', '--help'], timeout=5,
                                             env=allowed_agent_environment())
                        features = run_bounded([binary, 'features', 'list'], timeout=5,
                                               env=allowed_agent_environment())
                        cache[key] = (resume.returncode == 0 and all(flag in resume.stdout for flag in required)
                                      and features.returncode == 0
                                      and any(line.split()[:1] == ['skip_host_skill_discovery']
                                              for line in features.stdout.splitlines()))
                except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded):
                    cache[key] = False
        if not cache[key]:
            raise RuntimeError(engine.title() + ' cannot isolate rules with this CLI version. Update the CLI in Terminal, or turn off Private Pip and Draft only.')
        if engine == 'claude':
            return ['--safe-mode']
        return ['--ignore-user-config', '--ignore-rules', '-c', 'project_doc_max_bytes=0',
                '-c', 'project_doc_fallback_filenames=[]', '-c', 'developer_instructions=""',
                '-c', 'features.skip_host_skill_discovery=true', '-c', 'skills.bundled.enabled=false',
                '-c', 'skills.include_instructions=false', '-c', 'features.skill_search=false',
                '-c', 'features.external_agent_memory_import=false',
                '-c', 'features.plugins=false', '-c', 'features.remote_plugin=false',
                '-c', 'features.plugin_sharing=false']

    def explicit_agent_context(self, agent):
        from hub import HubError
        folder = Path(agent['path']).resolve()
        sections = []
        for filename, limit in (('CLAUDE.md', 16000), ('AGENTS.md', 16000), ('NOTES.md', 8000)):
            path = folder / filename
            try:
                with open_validated_file(path, [folder]) as stream:
                    value = stream.read(limit * 4).decode('utf-8', errors='replace')[:limit]
            except (HubError, OSError, ValueError):
                continue
            if agent.get('private_pip'):
                # A linked folder is never rewritten just to change access.
                value = re.sub(r'^@[^\n]*BOTS\.md\n+', '', value, flags=re.M)
            sections.append(filename + ':\n' + value)
        return '\n\n'.join(sections)

    def update_agent_rules(self, body):
        from hub import HubError
        if type(body.get('use_global_rules')) is not bool:
            raise HubError(400, 'Choose whether to use global rules.')
        return dict(self.edit_agent({'id': body.get('id'), 'use_global_rules': body['use_global_rules']}),
                    session_reset=True)

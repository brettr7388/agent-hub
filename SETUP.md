# Setup and configuration

## First run

Install Python 3.9+ and Claude Code, Codex CLI, or both. Sign into the CLI you plan to use, then run:

```sh
python3 hub.py
```

Open `http://127.0.0.1:4700` and sign in with the login token shown once in the terminal. Save it for later logins. If you lose it, stop Hub and run [`python3 hub.py --reset-token`](README.md#quick-start). Start with Guide's greeting and choose a starter prompt. Computer discovery is optional: open Settings → General → Scan this computer when you want to review local project and tool metadata before asking Guide for suggestions. The scan does not run automatically.

The token hash is stored in `data/auth.json`. To replace a lost token, stop Hub and run `python3 hub.py --reset-token`; this commits revocation of existing browser sessions before saving the new token hash. Protect the terminal output containing the new token. If saving the new auth file fails, the old token remains usable for a fresh login; rerun the reset command. If the process is interrupted after session revocation, existing sessions are logged out; rerun the reset command to finish and print a new token.

## Phone access

Hub binds to `127.0.0.1` by default. Install Tailscale on the macOS or Linux host and phone and join them to the same tailnet. From Terminal in the Hub folder, run `python3 hub.py --tailscale` to inspect local Tailscale status and print a `tailscale serve` command. Run that exact Serve command in Terminal, then restart Hub. The HTTPS link is printed in the terminal and appears in Settings → General → Phone setup. Open it on your phone. Hub does not enable Serve itself. Keep the listener loopback-only; Funnel and public port forwarding are unsupported.

## Services

Install a background service only when you explicitly choose to:

```sh
python3 hub.py --service install
```

On macOS, Hub creates a LaunchAgent. On Linux, it prints a systemd user unit for review. To remove the service, run `python3 hub.py --service uninstall` and follow the printed instructions. Normal startup does not install a service.

## Configuration

Hub creates `config.json` on first start. Copy values from `config.example.json` as needed, then restart after hand edits. To change the listening port, stop Hub, set `port` in `config.json` (for example, `4800`), and start Hub again; open `http://127.0.0.1:4800`. Common options include `port`, `bind`, `agents_dir`, `max_parallel`, `turn_timeout`, `route_timeout`, and `allowed_origins`. HTTPS origins are used with Tailscale Serve. `external_agent_dirs` can point to directories containing existing Pips; archived Pips, including linked and Hub-created Pips, can be restored from All Pips → Show hidden → Unarchive. Archiving a chat is separate and keeps its history in local storage.

The default bind is loopback. A non-loopback bind requires the explicit `allow_lan_bind` option and is discouraged. Upload limits can be set with `max_upload_bytes` and `max_total_upload_bytes`. Keep the checkout and `data/` directory private.

Settings → Connections keeps the approvals connector under **Advanced**. Connect an external approvals queue that speaks the Agent Hub approvals API — most people don't need this. Configure `approvals_url` with the service's loopback HTTP address, for example `http://127.0.0.1:PORT`. Existing installations may still use an older config key; Hub reads it for compatibility, but new configuration should use `approvals_url`.

## Storage and backups

Chats, settings, and upload references live under `data/`; Hub-created Pip files live under `agents/` by default. Back up these directories and any configured linked Pip folders with Hub stopped. Provider account files and login tokens are not part of an export. Exports include your chat text. Review before sharing — we redact obvious secrets but can't catch everything. Keep backups private because chat text and agent instructions may contain sensitive information.

## Discovery and permissions

Discovery scans selected local sources and shows the information it will use before suggesting Pips. Suggestions are optional and require an explicit request. Treat project names and descriptions as private metadata. Agent permissions depend on the chosen CLI and settings; Draft only applies a restricted tool profile but does not create a full computer sandbox.

For detailed security boundaries, see [SECURITY.md](SECURITY.md). To run the local test suite, see [CONTRIBUTING.md](CONTRIBUTING.md).

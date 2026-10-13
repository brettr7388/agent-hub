# Browser & passwords

Settings → Connections → **Pip browser** opens Chrome on the Hub host. From a
phone, the window opens on the host computer; the phone can tap **Done** afterwards.
Enable **Can use Pip browser** in a Pip's settings to provide its Chrome DevTools
MCP. Private Pip and Draft only cannot use Pip browser. Full-access Pips also
inherit browser tools from their normal CLI configuration, including Claude in
Chrome when available. Neither browser is the only one a full-access Pip may reach.

The profile is fixed at `data/pip-browser-profile`, independently of the owner's
everyday Chrome. Chrome starts on demand with `--user-data-dir` pointing there
and a remote-debugging pipe. Hub owns a 0700 directory and 0600 Unix socket/proxy, with no public
TCP DevTools endpoint. Another process running as the same OS user may still
control the socket or profile. Hub closes the browser on normal shutdown; logins
and cookies survive in the profile for the next start. A browser left running by
an older Hub version cannot attach through the pipe and must be closed once.
**Sign out everywhere** asks for a second tap, closes the Pip browser, and removes only that profile. It does not revoke
remote sessions on other devices or remove saved logins from the OS vault.

The Hub resolves an already-installed Chrome DevTools MCP executable or cached
package without invoking npx or downloading anything. It supplies a per-run
browser endpoint under the canonical `chrome-devtools` server name, and disables
MCP usage statistics and CrUX requests.
Full-access Claude can also inherit its everyday Claude in Chrome integration.
No global CLI configuration is edited. For other installations, `config.json`
accepts `pip_browser_bin`, `pip_browser_mcp_command`, and
`pip_browser_mcp_args` (a list of local executable arguments).

A Pip can emit either standalone fenced request:

```agent-hub
{"action":"signin_request","site":"tiktok.com","reason":"to read your inbox"}
```

```agent-hub
{"action":"login_fill_request","site":"tiktok.com"}
```

The first card opens the site in the Pip browser. **Done** sends
`I signed in to tiktok.com` to the requesting Pip, including in a group. Done is
an owner's confirmation, not a claim that Hub has inspected the site's session.
The second card shows the account username before **Approve fill** or **Don't**,
even when only one account matches. The first Choose account tap does not approve.
Every request needs its own fresh tap. Browser actions are claimed
durably before execution; uncertain actions are not replayed after a crash.
Known status replies use a recoverable, idempotent notification record.

Saved logins are optional. On macOS the Hub uses the Keychain `security` CLI, service **Agent Hub**,
account **<domain>:<username>**. Passwords are passed through stdin, never command
arguments. A separate Keychain item holds the account list and explicit allowed
subdomains; there is no credential index in the Hub database or a plaintext file.
Linux uses `secret-tool` through stdin when installed; otherwise this feature is
hidden. Add/delete may require unlocking or granting OS vault access.

Internet sites must be exact registrable domains, checked against a bundled offline
Public Suffix List, including private suffixes. Each additional subdomain must be
listed explicitly. Wildcards and URLs are not accepted. Saved internet sites cannot
contain ports. **For local tests only**, saved sites and sign-in requests can use
exact `localhost:<port>` or `127.0.0.1:<port>`; that port is retained for opening
and filling. Legacy bare `localhost` or `127.0.0.1` entries can match any local
port. The fill checks the Pip's pinned login tab and its top-level origin, requires
HTTPS on the default port for internet sites, and targets the selected username
and password fields in the top document. It refuses if the frame, origin, or node
identity changes. It does not traverse iframes, accept ambiguous fields, or submit
the form. After “Filled,” click Sign in in that tab without reloading.

Never paste passwords into chat. The Hub sends only fill status to the Pip, keeps
credentials out of chats/prompts/logs/exports, and excludes browser profile files
from its exports. Follow Anthropic's Claude in Chrome safety guidance, use a
separate profile, and consider **1Password for Claude** as an alternative.

## CLI boundaries

The installed Claude and Codex CLIs run tools as the owner's OS user. They cannot
guarantee that an unrestricted agent cannot read Keychain, browser credential files,
or a password already placed in a page. The broker keeps values out of its own
model-facing paths; it is not a separate OS security principal. A prompt-injected
full-tool Pip can invoke the OS vault CLI directly under the owner's account,
despite the fresh fill approval. For saved-login sites, use a Private Pip for advice
and operate the site manually; Private Pip cannot automate Pip browser. Private Pip
removes default integrations but is not an OS sandbox or an absolute barrier to
same-user vault access. Do not grant browser or shell tools to an untrusted Pip.

Per-run MCP overrides replace the canonical `chrome-devtools` connection. Other
user-configured MCP server names remain available to preserve the full-tool
behavior owned by section A. A separately named browser server can still expose
an everyday profile; remove those servers from the Pip's configuration if strict
browser separation is required. Arbitrary full-tool shell commands can likewise
access the owner's computer. The Hub itself never discovers or attaches to the
everyday Chrome profile.

The offline suffix list was copied unchanged from the locally installed
`public_suffix` 4.0.7 package, whose list retains its original MPL 2.0 notice and
source URL. Updating it requires replacing the snapshot deliberately; no runtime
network lookup occurs.

## Verification

Python tests use fake macOS `security`, Linux `secret-tool`, model CLIs, and CDP.
They cover request parsing, domain validation, origin/TLS/iframe/focus refusal,
profile boundaries, approval replay prevention, notification recovery, and planted
credential canaries in SQLite/files/logs/prompts/export ZIP entries. JS smoke tests
exercise cards, account choice, secret-field clearing, settings, and
attachment preservation. Real OS vault dialogs and a live Chrome sign-in require
host testing; automated tests do not use real accounts or send site requests.

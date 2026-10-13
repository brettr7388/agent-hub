# Security

## Threat model

Agent Hub is a single-owner application for a trusted user's computer. Its login token protects the Hub interface from other users on the network. It is not a multi-user boundary or a sandbox for untrusted agents. A Pip can use the tools available to its CLI, and prompts and files it reads may be sent to the model provider. Review instructions, outputs, and proposed actions before proceeding.

Hub stores chats and settings locally. Keep the checkout, token, and backups private. Draft only limits available CLI tools, but does not isolate the computer or make arbitrary agent instructions safe.

If you reset a lost token, Hub commits session revocation before replacing the saved token hash. If writing the new auth file fails, the old token still works for a fresh login; rerun `python3 hub.py --reset-token`. If Hub stops after revoking sessions but before finishing the reset, current browser sessions are logged out; rerun the command to complete the reset and print a new token.

## Network model

Hub listens on loopback (`127.0.0.1`) by default. Non-loopback binding requires the explicit `allow_lan_bind` setting and produces a warning because it exposes the login interface to the local network. HTTPS origins configured for Tailscale Serve are accepted only when their requests arrive from loopback, as the Serve proxy connects locally. Use Tailscale Serve for tailnet-only phone access. Funnel, public port forwarding, and direct public exposure are unsupported.

Hub caps handlers at 48, allows at most eight concurrent unauthenticated connections per source IP and 16 overall, and reserves the remaining capacity for authenticated sessions. It recognizes complete session-cookie headers without blocking the accept loop. Header reads have a 10-second deadline; JSON bodies have 30 seconds; uploads have a total deadline of at least 30 seconds, scaled at 32 KiB per second. These controls bound slow requests; they are not protection against a hostile local process.

Tailscale Serve forwards connections from loopback, so its users share the per-source quota. For deployments with an additional configurable reverse proxy, cap upstream concurrency at 48 and its header deadline at 10 seconds as well; keep the upstream listener on loopback. Do not assume Serve itself supplies these limits. A valid Hub token grants broad access to the owner's chats and agents; do not share it.

## Reactions

👍 and ✅ intentionally mean approval of what the reacted-to message proposed. On an approval or Guide proposal card, the reaction follows the card's normal primary action and confirmation path. On a plain message, it approves only that message's proposal; the Pip's Draft only setting and any approval gates in its instructions still apply. 👎 declines, and ❓ requests an explanation. Reactions can be misread as broader consent, so Hub scopes approval to the message and requires the existing card confirmation. Pips should acknowledge every approval, decline, or question.

## Group handoffs and routing

In a group you create, structured handoffs run automatically. A handoff requires a final standalone `@@handoff target-name: task` line outside quotes and code blocks; an ordinary `@name` mention does not delegate work. Hub strips the marker from visible text and gives the receiving Pip the full original request and sender message. Handoffs are limited to three per chain. A handoff routes context; it does not itself write files or send anything outside Hub. It does not change the recipient's engine, Draft only setting, or other permissions; the receiving Pip's own settings continue to govern its actions. When group routing is ambiguous, Claude may classify the request in an isolated, tools-disabled call. Codex has no verified tool-free classifier mode, so Hub uses a deterministic fallback: the last responder if still in the group, otherwise the first Pip in the group.

## Exports

Exports include your chat text. Review before sharing — we redact obvious secrets but can't catch everything. Pattern screening reduces exposure but cannot guarantee that chat text, instructions, or other included content is free of sensitive information. Authentication and provider token files are excluded.

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** feature for this repository. Include the affected version, impact, and a minimal reproduction. Do not include live tokens, credentials, private chat content, or other users' data. We will acknowledge reports and coordinate a fix before public disclosure where practical.

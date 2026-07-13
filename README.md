# Echo — close your WhatsApp loops

Echo turns your WhatsApp into two lists: **what you owe people** and **what people owe you** —
plus a graveyard sweep for balls you dropped weeks ago. It runs entirely on your machine,
never marks anything read, never sends without your explicit click, and gets smarter every
time your AI assistant (Claude Code, Claude Cowork, or any agent that can read files and run
shell commands) looks at it.

```
Your phone (primary) ──► wacli linked device ──► local SQLite mirror (~/.echo)
                                                    │
                              mechanical engine (python, launchd, every 15 min)
                              → close-the-loop / chase / dropped-balls queues
                                                    │
                              your AI = judgment layer (verdicts, drafts, priorities)
                              → thread_state.json (persistent brain)
                                                    │
                              local dashboard  http://127.0.0.1:8787
```

## Privacy model

- Everything lives in `~/.echo/` on your machine. Delete the folder = everything gone.
- Sync is a [wacli](https://github.com/openclaw/wacli) linked device (official WhatsApp
  multi-device protocol, same as WhatsApp Web). Reads never produce read receipts.
- No cloud, no telemetry. The only network traffic is WhatsApp's own protocol.
- Sends happen only when YOU click Send (or explicitly tell your agent "send it").

## Install (macOS)

```bash
git clone https://github.com/shubham-khetan/echo-wa && cd echo-wa
./install.sh        # installs wacli via Homebrew, pairs via QR, starts the daemons
```

Then open http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html (or run `./make_app.sh` for a
Dock app called Echo).

## The self-starter: let your AI configure it

Echo ships dumb and becomes smart through your own AI assistant. After install, open
Claude Code (or any file-capable agent) in this folder and say:

> **bootstrap echo**

The agent follows `skills/echo-intelligence/SKILL.md`, which tells it to:

1. Scan your mirrored chats and auto-classify groups (≤15 members = working group treated
   like a DM; 100+ members or 5+ active senders/day = clutter, swept every 2 days).
2. Read whatever context you already have (task lists, CRM, notes, calendar) and rate each
   thread's importance — your investor ≠ your bank's RM.
3. Build `CHAT_MAP.csv` (person ↔ chat ids, 1:many) so future runs can pull any person's
   threads instantly.
4. Write verdicts into `thread_state.json` — the persistent brain the dashboard renders.
5. Learn your language: every ack-phrase or commitment-phrase the regex engine missed
   (any language — Hinglish included) gets appended to `heuristics_config.json`.
6. Repeat on demand: the dashboard's 🧠 button copies the re-run prompt to your clipboard.

Every mute you click (🔕) is logged to `feedback_log.csv` — the agent reads it and learns
what you consider noise. The system compounds.

## Files (all in ~/.echo after install)

| File | Owner | What |
|---|---|---|
| `store/wacli.db` | sync daemon | SQLite mirror (FTS5 search) |
| `thread_state.json` | your AI | per-thread verdicts: status/priority/next action |
| `heuristics_config.json` | your AI appends | closers, commitments, requests — the lexicons |
| `label_overrides.csv` | you / your AI | force a chat's tier |
| `CHAT_MAP.csv` | your AI | person ↔ jid map (1:many) |
| `feedback_log.csv` | dashboard | your mutes = training signal |
| `infra/` | — | engine, server, launchd plists |

## Uninstall

```bash
launchctl bootout gui/$(id -u)/sh.echo.sync; launchctl bootout gui/$(id -u)/sh.echo.dashboard
rm -rf ~/.echo ~/Library/LaunchAgents/sh.echo.*.plist
```
…and remove the linked device in WhatsApp → Settings → Linked devices.

## Credits

Built on [wacli](https://github.com/openclaw/wacli) / [whatsmeow](https://github.com/tulir/whatsmeow).
Not affiliated with WhatsApp/Meta; linked-device use is subject to WhatsApp's terms. MIT.

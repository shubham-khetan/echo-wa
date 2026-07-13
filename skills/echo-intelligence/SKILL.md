# Echo Intelligence — bootstrap & recurring runs

> For the user's AI assistant (Claude Code / Cowork / any file+shell-capable agent).
> Data root: `~/.echo/`. DB is read-only SQLite: `sqlite3 -readonly ~/.echo/store/wacli.db`.
> Dashboard: http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html · re-render: `curl -s http://127.0.0.1:8787/refresh`

## Hard rules (non-negotiable)

1. READ-MOSTLY. Never send a message unless the user explicitly says "send it" (the dashboard's
   Send button is the user's own action). Never mark anything read — reads can't anyway.
2. Message content stays in `~/.echo/`. If you maintain external notes/CRM for the user, copy
   CONCLUSIONS ("X owes Y a proposal since Jun 3"), never quoted messages.
3. No media downloads unless asked.

## BOOTSTRAP (first run — "bootstrap echo")

1. Inspect the mirror: total messages, chats by kind, distinct senders/day per group.
2. Classify: groups ≤15 members = `working-group` (treat like DMs); 16–100 & <5 senders/day =
   `signal-group`; 100+ members or ≥5 senders/day = `clutter`. Personal/family chats = `personal`;
   pure service blasts = `ignore` — BUT check each window for live commitments first (a bank RM
   can owe a document tomorrow). Write exceptions to `label_overrides.csv`.
3. Learn who matters: read whatever context the user has (task lists, notes, CRM, calendar) or
   interview the user briefly ("who are the 10 people whose messages you must never miss?").
   Build `CHAT_MAP.csv` (name,jid,kind,slug — 1:many, one person can have several chats).
4. First verdict pass (see schema below) over the last 14 days + a dropped-ball triage of the
   engine's `dropped` queue. Draft follow-ups into `claude_data.js`.
5. Learn the user's language: sample closed threads; ack-phrases and commitment-phrases the
   engine missed (ANY language) get appended to `heuristics_config.json`.
6. Set `STATE.json.last_processed` = now. `curl /refresh`. Report the two queues to the user.

## RECURRING RUN ("run echo intel" / 🧠 button)

1. Re-verdict all ⟳-stale items (new messages since verdict) with fresh 20-message context.
2. Curate heuristic queue items: promote real → verdicts; close noise. Judge with the user's
   PRIORITIES (their project/task context), not message mechanics.
3. Meeting-flagged (📅) threads: cross-ref the user's calendar — a discussed/cancelled meeting
   with no future event = chase.
4. Triage `dropped` (tracked chats silent 7–45d ending unresolved): real → verdict+draft,
   dead → closed.
5. Respect feedback: `feedback_log.csv` rows (`ts,mute,jid,name`) tell you what the user calls
   noise — mirror that pattern in future labels/verdicts.
6. Append newly-learned phrases to `heuristics_config.json`. New people → `CHAT_MAP.csv`.
7. Update `claude_data.js` (drafts each with jid, commitments, group_notes), advance
   `STATE.json.last_processed`, `curl /refresh`, report the DELTA only.

## Verdict schema — `thread_state.json`, keyed by chat jid

```json
{"status": "close_loop|chase|closed|snoozed", "who_owes": "me|them", "priority": 1,
 "what": "situation ≤140c", "next_action": "concrete move", "due": "YYYY-MM-DD",
 "anchor_ts": 0, "verdict_ts": 0, "source": "claude|user-mute"}
```
Priority: 1 = money/customers/critical · 2 = network/projects · 3 = personal.
Engine merge rules: verdicts OVERRIDE labels (even `ignore`); messages newer than `anchor_ts`
flag ⟳ re-evaluate; snoozed/closed auto-reopen on new inbound. Set `anchor_ts` = chat MAX(ts).

## Group sweeps

`clutter` + `signal-group` chats: sweep max once per 2 days (`STATE.json.last_group_sweep`),
extract 1–3 genuine signals, never write recaps.

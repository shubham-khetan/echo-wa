# WhatsApp Intelligence Run

> The judgment layer over the local WhatsApp mirror. Any session can run this — triggered by the
> dashboard's 🧠 button, "what's on WhatsApp", or automatically inside CoS runs (MODE_COS Step 3c).
> The mechanical engine runs without Claude; THIS skill is what makes it smart. Built Jul 12 2026.

## ⚡ LEAN MODE — this is the DEFAULT. Keep runs quick.

Unless Shubham explicitly asks for a "deep" / "full" run, do ONLY this (2-3 min, incremental):

1. Read `STATE.json` last_processed. Pull ONLY messages since then (osascript + sqlite3 on
   `store/wacli.db`) — not the whole board.
2. For chats with NEW activity only: update their entry in `thread_state.json` — flip status
   (close_loop / chase / closed), refresh what / next_action / anchor_ts. Add genuinely new loops;
   close ack-only threads. Leave unchanged chats untouched — do NOT re-verdict everything.
3. Refresh `claude_data.js` drafts ONLY for items that moved. Keep drafts short.
4. Set `STATE.json` last_processed = now. `curl -s http://127.0.0.1:8787/refresh`.
5. Report a 2-3 line delta (what changed). Done.

**SKIP in lean mode** (only do when Shubham asks): calendar cross-ref, deep dropped-ball scan,
lexicon edits to `heuristics_config.json`, ACTIVE_THREADS backfill, group sweeps. The full
procedure below is the DEEP run — reference it only on explicit request.

---

## System map (real location: `~/.echo/` — symlinked as `Master Project/whatsapp`)

⚠️ File tools + sandbox canNOT follow the symlink. ALL file/DB access via `mcp__Control_your_Mac__osascript`.

| File | Owner | Purpose |
|---|---|---|
| `store/wacli.db` | sync daemon | SQLite mirror (read-only queries: `sqlite3 -readonly`) |
| `thread_state.json` | **Claude** | Per-jid verdicts — the persistent brain |
| `heuristics_config.json` | **Claude appends** | Closer/commitment/request lexicons (incl. Hinglish) |
| `label_overrides.csv` | **Claude** | jid,label,note — dm/working-group/signal-group/clutter/personal/ignore |
| `claude_data.js` | **Claude** | Drafts (with jid!), commitments, group_notes for dashboard |
| `dashboard_data.js` | engine | Auto-generated — never hand-edit |
| `STATE.json` | **Claude** | last_processed cursor + last_group_sweep |
| `infra/` | — | engine (wa_dashboard_refresh.py), server (wa_dashboard_server.py), plists |

Dashboard: http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html · server endpoints: /refresh /search?q= /send /intel

## Verdict schema (thread_state.json, keyed by jid)

`status`: close_loop (Shubham owes) | chase (they owe) | closed | snoozed
`priority`: 1 = round/customer/revenue (P1 red) · 2 = network/podcast/intros · 3 = personal
`what` (situation, ≤140c) · `next_action` (concrete move) · `due` (ISO date) ·
`anchor_ts` (newest message ts the verdict covers — set to chat's MAX(ts)) · `verdict_ts` · `source: claude`

**Merge rules the engine enforces:** verdicts OVERRIDE labels (an `ignore` chat with a live verdict
still surfaces — the Manu-HDFC lesson). New messages after anchor_ts ⇒ item flagged ⟳ re-evaluate.
closed/snoozed + new inbound ⇒ auto-reopens as heuristic.

## The run (every time)

1. `TZ='Asia/Kolkata' date` first. Read STATE.json + thread_state.json.
2. **Re-verdict every ⟳-stale item**: pull last ~20 msgs of that chat, decide fresh, update anchor_ts to MAX(ts).
3. **Curate heuristic items** in both queues (dashboard_data.js): promote real ones to verdicts,
   close noise. Judge with PROJECT CONTEXT — read ACTIVE_THREADS priority stack; what maps to a
   tier gets priority 1-2; Sourav-ICICI-type service noise gets `closed` or label `ignore`
   **but check the window for live commitments first** (Manu had a Monday deliverable).
4. **Calendar cross-ref** every meeting-flagged (📅) thread: meeting discussed/cancelled with no
   future calendar event = chase (the Rinu/Milkymist pattern). Use calendar search_events.
5. **New-intro detection**: new people in threads (Gunjan, Vardhan pattern) → PEOPLE_INDEX.yaml
   entry + surface as lead.
6. **Learn**: any closer/commitment/request phrasing the engine missed (esp. Hinglish — "call
   karte", "bhej dunga") → APPEND to heuristics_config.json.
7. **Backfill (auto-write, Shubham approved Jul 12)**: conclusions → ACTIVE_THREADS (reconcile,
   don't append; quotes NEVER leave ~/.wacli-cos — only conclusions). New people → people files/index.
   Two-way: ACTIVE_THREADS may correct WA verdicts too (Abhinav cheque-already-in lesson).
8. **Refresh claude_data.js**: send-ready drafts (each with jid so the dashboard can send),
   commitments list, group_notes. Advance STATE.json last_processed to now.
9. **Group sweep** only if last_group_sweep ≥2 days old or asked: clutter+signal groups, extract
   1-3 real signals max, update last_group_sweep.
9b. **Dropped-ball curation**: the engine's `dropped` queue (CHAT_MAP-tracked chats + working
   groups, silent 7–45d, ended unresolved — Rajat/SPC + Osborne/orbitshift pattern) must be
   TRIAGED every run: promote real ones to verdicts with drafts, mark dead ones `closed` in
   thread_state.json so the queue stays short. Cross-ref ACTIVE_THREADS radar items — a dropped
   WA thread that matches a radar line ("Osborne message", "docs from Rajat") is priority 1.
9c. **Respect mute feedback**: `~/.wacli-cos/feedback_log.csv` (ts,mute,jid,name) = Shubham's
   explicit "this is noise" signals from the dashboard 🔕. Muted threads stay snoozed until new
   messages arrive; recurring mutes of similar chats = learn the pattern (label them down).
10. `curl -s http://127.0.0.1:8787/refresh` and report the DELTA to Shubham (what changed, what's
    newly burning), not an inventory.

## Send policy (unchanged, hard)

Drafts by default. Dashboard Send button = Shubham's explicit action (fine). Claude sends via CLI
only on explicit "send it". Never bulk. Reads never mark anything read.

## Ops quick-ref

Health: `launchctl list | grep wacli` (sync + dashboard) · sync log: `~/.wacli-cos/store/sync.log`
Engine manually: `python3 ~/.wacli-cos/infra/wa_dashboard_refresh.py`
Sends pause sync ~5s (store lock) — server handles bootout/bootstrap automatically.

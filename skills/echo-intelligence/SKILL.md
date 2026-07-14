# WhatsApp Intelligence Run

> The judgment layer over the local WhatsApp mirror. Any session can run this — triggered by the
> dashboard's 🧠 button, "what's on WhatsApp", or automatically inside CoS-style runs.
> The mechanical engine runs without the assistant; THIS skill is what makes it smart.

## ⚡ LEAN MODE — this is the DEFAULT. Fast, but NOT a dumb dump.

Unless explicitly asked for a "deep" / "full" run, do this (aim for 3-5 min — lean means scoped,
not shallow; the point is the user shouldn't have to think, you should):

1. Read `STATE.json` last_processed. Pull ALL messages since then across ALL chats (osascript +
   sqlite3 on `store/wacli.db`) — not just the tracked/known set. New activity in an untracked
   chat is exactly what a lazy run would miss.
2. **Re-verdict, don't just flag, every chat with new activity** — including chats already in
   `thread_state.json`. Read the actual new messages in context and update status/what/next_action/
   anchor_ts accordingly. A conversation that moved from "I owe them" to "they owe me" must flip
   buckets THIS run, not sit stale until a deep sweep. This is the single most important behavior.
3. **Discover genuinely new open threads**: any chat (tracked or not) with new activity that reads
   as an open loop gets added to thread_state.json even if it was never explicitly flagged before.
   Don't wait for a tracking file to say a chat matters — a live open thread matters on its own.
   (Chats marked `no`/`archive` in relevance_overrides.csv remain a hard exclusion.)
4. **Validate existing drafts before leaving them queued**: for every draft in claude_data.js, check
   whether the underlying thread moved since the draft was written. Stale/resolved drafts get dropped
   or rewritten — never leave a draft proposing something already said or no longer true.
5. Refresh `claude_data.js`: drafts for anything that changed, kept short and current.
6. Set `STATE.json` last_processed = now. `curl -s http://127.0.0.1:8787/refresh`.
7. Report a genuine delta — what moved, what's newly open, what you dropped/rewrote — in 3-5
   lines. Not an inventory dump, not silence either.

**SKIP in lean mode** (only do when asked): full calendar cross-ref, deep dropped-ball scan, lexicon
edits, activity backfill, group clutter/signal sweeps — these are expensive and rarely change
run-to-run. Everything above (re-verdicting, discovery, draft validation) is NOT optional — that's
the difference between a script and an assistant. The full procedure below is the DEEP run.

---

## System map (real location: `~/.echo/`)

⚠️ File tools + sandboxes often canNOT follow symlinks into this folder. Use direct OS-level file/DB
access (osascript on macOS, or a shell tool) for everything here.

| File | Owner | Purpose |
|---|---|---|
| `store/wacli.db` | sync daemon | SQLite mirror (read-only queries: `sqlite3 -readonly`) |
| `thread_state.json` | **assistant** | Per-jid verdicts — the persistent brain |
| `heuristics_config.json` | **assistant appends** | Closer/commitment/request lexicons (incl. Hinglish) |
| `label_overrides.csv` | **assistant** | jid,label,note — dm/working-group/signal-group/clutter/personal/ignore |
| `relevance_overrides.csv` | **you** (via dashboard 👍/👎 or chat) | jid,relevant,priority,note — HARD gate, overrides labels + verdicts + heuristics |
| `claude_data.js` | **assistant** | Drafts (with jid!), commitments, group_notes for dashboard |
| `dashboard_data.js` | engine | Auto-generated — never hand-edit |
| `STATE.json` | **assistant** | last_processed cursor + last_group_sweep |
| `infra/` | — | engine (wa_dashboard_refresh.py), server (wa_dashboard_server.py), plists |

Dashboard: http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html · server endpoints: /refresh /search?q= /send /intel /relevance /flip /dismiss-draft

## Verdict schema (thread_state.json, keyed by jid)

`status`: close_loop (you owe) | chase (they owe) | closed | snoozed
`priority`: 1 = highest priority · 2 = normal · 3 = personal/low
`what` (situation, ≤140c) · `next_action` (concrete move) · `due` (ISO date) ·
`anchor_ts` (newest message ts the verdict covers — set to chat's MAX(ts)) · `verdict_ts` · `source: assistant`
(`source` also takes `user-mute`, `user-flip`, `user-dismiss` — all three are hard user overrides
and should never be silently reversed by a re-verdict; if the situation genuinely changed, ask or let
new messages trigger the ⏳-stale path naturally.)

**Merge rules the engine enforces:** verdicts OVERRIDE labels (an `ignore` chat with a live verdict
still surfaces). New messages after anchor_ts ⇒ item flagged ⟳ re-evaluate.
closed/snoozed + new inbound ⇒ auto-reopens as heuristic.

## Manual overrides (dashboard)

Three self-serve controls in the UI so corrections do not need to route through a chat session:

- **🎛 Manual override tab**: search ANY chat (group or DM, even ones that never surfaced
  before) and set relevant=yes/no/archive directly — same `/relevance` endpoint and
  `relevance_overrides.csv` gate described below. Fastest way to pre-triage a chat before it ever
  shows up as noise.
- **✕ dismiss on drafts**: each draft in claude_data.js has a dismiss button. Hitting it calls
  `/dismiss-draft`, which writes `thread_state.json[jid] = {status: closed, source: user-dismiss}`
  and removes the draft from claude_data.js. Treat this like an assistant-authored `closed` verdict
  — do NOT re-open it in a future run unless genuinely new messages arrive after the dismiss.
- **⇄ flip on close_loop/chase cards**: corrects a wrong bucket call directly — flips
  close_loop↔chase via `/flip`, writing a `source: user-flip` verdict. If a future run's own
  classification disagrees with a `user-flip`/`user-dismiss`/`user-mute` verdict, trust the user's
  override, not the heuristic.

## Relevance layer (`relevance_overrides.csv`) — the deterministic, permanent yes/no list

This sits ABOVE everything else — built so the heuristic stops re-litigating group relevance
every run. Columns: `jid,relevant,priority,note`.

- `relevant=no` or `archive` ⇒ chat is excluded from close_loop/chase/since_last/dropped, full stop,
  no matter what a verdict or heuristic says. `archive` = "served its purpose, done" (e.g. an
  intro-only group); `no` = "just noise" (e.g. a large beta-users group).
- `relevant=yes` ⇒ chat always surfaces even if its mechanical `label` is ignore/clutter/signal-group.
- `priority=low` ⇒ still surfaces but ranks lowest.
- `priority=activity_only` ⇒ chat is EXCLUDED from the standing `dropped`-balls queue (it never sits
  there silently accruing "silent Nd" pressure) but still surfaces normally via since_last/main loop
  the moment there's genuinely new activity. Use this for chats that only matter when something new
  actually happens.
- Anything NOT in this file falls back to the old heuristic path (label_overrides + engine
  classification) and should only be swept/reconsidered in a **weekly** pass, not every run — this is
  what keeps lean-mode runs quick. Only escalate an untriaged chat mid-week if it's clearly urgent.
- Add rows two ways: (a) tell the assistant in chat ("mark X not relevant") — append/update a row
  directly; (b) click 👍/👎 on any group-ish card in the dashboard, which POSTs to `/relevance` and
  the server appends/updates the row and re-runs the engine automatically. Both paths are equally
  canonical — always keep the file as the single source of truth, never duplicate the list elsewhere.

## The run (every time — DEEP mode only)

1. `date` first. Read STATE.json + thread_state.json.
2. **Re-verdict every ⟳-stale item**: pull last ~20 msgs of that chat, decide fresh, update anchor_ts to MAX(ts).
3. **Curate heuristic items** in both queues (dashboard_data.js): promote real ones to verdicts,
   close noise. Judge with your real priorities — what maps to something important gets priority 1-2;
   service-RM-type noise gets `closed` or label `ignore` **but check the window for live commitments first**.
4. **Calendar cross-ref** every meeting-flagged (📅) thread: meeting discussed/cancelled with no
   future calendar event = chase.
5. **New-intro detection**: new people in threads → your people/contacts index entry + surface as lead.
6. **Learn**: any closer/commitment/request phrasing the engine missed (esp. any local-language
   phrasing) → APPEND to heuristics_config.json.
7. **Backfill**: conclusions → your task/notes system (reconcile, don't append; quotes NEVER leave
   `~/.echo` — only conclusions).
8. **Refresh claude_data.js**: send-ready drafts (each with jid so the dashboard can send),
   commitments list, group_notes. Advance STATE.json last_processed to now.
9. **Group sweep** only if last_group_sweep ≥2 days old or asked: clutter+signal groups, extract
   1-3 real signals max, update last_group_sweep.
9b. **Dropped-ball curation**: the engine's `dropped` queue (tracked chats + working groups,
   silent 7–45d, ended unresolved) must be TRIAGED every run: promote real ones to verdicts with
   drafts, mark dead ones `closed` in thread_state.json so the queue stays short.
9c. **Respect mute feedback**: `~/.echo/feedback_log.csv` (ts,mute,jid,name) = your explicit
   "this is noise" signals from the dashboard 🔕. Muted threads stay snoozed until new messages
   arrive; recurring mutes of similar chats = learn the pattern (label them down).
9d. **Respect relevance_overrides.csv** (see section above) — this is a HARD gate, checked before
   any other logic. Never re-surface a `no`/`archive` chat by "fixing" a verdict around it.
10. `curl -s http://127.0.0.1:8787/refresh` and report the DELTA (what changed, what's newly
    burning), not an inventory.

## Send policy (unchanged, hard)

Drafts by default. Dashboard Send button = your explicit action (fine). The assistant sends via
CLI only on explicit "send it". Never bulk. Reads never mark anything read.

## Ops quick-ref

Health: `launchctl list | grep echo` (sync + dashboard) · sync log: `~/.echo/store/sync.log`
Engine manually: `python3 ~/.echo/infra/wa_dashboard_refresh.py`
Sends pause sync ~5s (store lock) — server handles bootout/bootstrap automatically.

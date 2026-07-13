#!/usr/bin/env python3
"""Thread-state engine v4 — mechanical layer.
v4: Claude verdicts OVERRIDE labels (an 'ignore' chat with a live verdict still surfaces —
the Manu-HDFC lesson); priority ranking from Master Project context (1=round/customer,
2=network, 3=personal); jid on every item so the dashboard can draft+send against it.
Claude runs own thread_state.json + heuristics_config.json (the improvement loop)."""
import sqlite3, json, csv, os, re, time, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "store", "wacli.db")
OUT = os.path.join(BASE, "dashboard_data.js")
OVR = os.path.join(BASE, "label_overrides.csv")
CFG = os.path.join(BASE, "heuristics_config.json")
TS = os.path.join(BASE, "thread_state.json")
ST = os.path.join(BASE, "STATE.json")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
now = int(time.time())

cfg = json.load(open(CFG))
closers = [re.compile(p, re.I) for p in cfg["closers"]]
commit_re = re.compile("|".join(cfg["commitment_patterns"]), re.I)
request_re = re.compile("|".join(cfg["request_patterns"]), re.I)
meeting_re = re.compile("|".join(cfg["meeting_patterns"]), re.I)

state = {}
if os.path.exists(TS):
    try: state = json.load(open(TS))
    except Exception: state = {}
last_processed = 0
if os.path.exists(ST):
    try: last_processed = json.load(open(ST)).get("last_processed") or 0
    except Exception: pass

overrides = {}
if os.path.exists(OVR):
    for row in csv.DictReader(open(OVR)):
        overrides[row["jid"].strip()] = row["label"].strip()

def is_closer(t):
    t = (t or "").strip()
    return len(t) <= cfg["closer_max_len"] and any(p.search(t) for p in closers)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

chats = {}
for r in con.execute("""SELECT c.jid, c.kind, COALESCE(NULLIF(c.name,''),c.jid) name,
    (SELECT COUNT(*) FROM group_participants gp WHERE gp.group_jid=c.jid) members,
    (SELECT COUNT(DISTINCT sender_jid||date(ts,'unixepoch')) FROM messages
      WHERE chat_jid=c.jid AND ts >= :w)/7.0 spd
    FROM chats c WHERE c.kind IN ('dm','group')""", {"w": now-7*86400}):
    jid = r["jid"]
    if jid in overrides: label = overrides[jid]
    elif r["kind"] == "dm": label = "dm"
    elif r["members"] <= 15: label = "working-group"
    elif r["members"] <= 100 and r["spd"] < 5: label = "signal-group"
    else: label = "clutter"
    chats[jid] = dict(name=r["name"], label=label)

def recent_msgs(jid, n=3):
    rows = con.execute("""SELECT from_me, ts, COALESCE(NULLIF(sender_name,''),'') sn,
        COALESCE(NULLIF(text,''), NULLIF(display_text,''), '') t
        FROM messages WHERE chat_jid=? AND reaction_to_id IS NULL AND revoked=0
        AND COALESCE(NULLIF(text,''), NULLIF(display_text,''),'') <> ''
        ORDER BY ts DESC LIMIT ?""", (jid, n)).fetchall()
    out = []
    for r in reversed(rows):
        who = "You" if r["from_me"] else (r["sn"].split()[0] if r["sn"] else "Them")
        d = datetime.datetime.fromtimestamp(r["ts"], IST).strftime("%b %d")
        out.append(f"{who} ({d}): " + r["t"].replace("\n", " ")[:80])
    return out

def classify(jid, wdays=None, upto=None, lenient=False):
    rows = con.execute("""SELECT from_me, ts,
        COALESCE(NULLIF(text,''), NULLIF(display_text,''), '') t
        FROM messages WHERE chat_jid=? AND reaction_to_id IS NULL AND revoked=0
        AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT ?""",
        (jid, now - (wdays or cfg["window_days"])*86400, upto or now, cfg["window_messages"])).fetchall()
    rows = [r for r in rows if r["t"]]
    if not rows: return None
    meeting_flag = any(meeting_re.search(r["t"]) for r in rows)
    subst = [r for r in rows if not is_closer(r["t"])]
    if not subst: return ("closed", "", rows[0]["ts"], meeting_flag)
    last = subst[0]
    age_d = (now - last["ts"]) / 86400
    def unfulfilled(side):
        for i, r in enumerate(subst):
            if r["from_me"] == side and commit_re.search(r["t"]):
                return None if [x for x in subst[:i] if x["from_me"] == side] else r
        return None
    theirs, mine = unfulfilled(0), unfulfilled(1)
    if not last["from_me"] and request_re.search(last["t"]):
        return ("close_loop", last["t"][:110], last["ts"], meeting_flag)
    if theirs and (now - theirs["ts"])/86400 >= cfg["chase_after_days"]:
        return ("chase", theirs["t"][:110], theirs["ts"], meeting_flag)
    if mine: return ("close_loop", mine["t"][:110], mine["ts"], meeting_flag)
    if not last["from_me"] and (lenient or age_d <= cfg["respond_within_days"]):
        return ("close_loop", last["t"][:110], last["ts"], meeting_flag)
    if last["from_me"] and age_d >= cfg["chase_after_days"] and request_re.search(last["t"]):
        return ("chase", last["t"][:110], last["ts"], meeting_flag)
    return ("closed", "", last["ts"], meeting_flag)

close_loop, chase, personal = [], [], []
active = {r[0] for r in con.execute("SELECT DISTINCT chat_jid FROM messages WHERE ts >= ?",
                                    (now - cfg["window_days"]*86400,))}
for jid in active | set(state.keys()):
    ch = chats.get(jid)
    if not ch: continue
    v = state.get(jid)
    label = ch["label"]
    # Without a Claude verdict: ignore/clutter/signal chats are skipped; unnamed DMs skipped.
    unnamed = ch["name"].endswith("@s.whatsapp.net") or ch["name"].endswith("@g.us")
    if not v and (label in ("ignore", "clutter", "signal-group") or unnamed): continue

    res = classify(jid) or ("closed", "", now, False)
    status, what, anchor, meet = res

    item = None
    if v and v.get("status"):
        newest = con.execute("SELECT MAX(ts) FROM messages WHERE chat_jid=? AND reaction_to_id IS NULL",
                             (jid,)).fetchone()[0] or 0
        stale = newest > v.get("anchor_ts", 0)
        if v["status"] in ("closed", "snoozed"):
            if stale and status != "closed" and label not in ("ignore",):
                item = dict(status=status, what=what, next="(reopened — new msgs after verdict)",
                            anchor=anchor, src="heuristic", stale=True, priority=v.get("priority", 2))
            else: continue
        else:
            item = dict(status=v["status"], what=v.get("what", what),
                        next=v.get("next_action", ""), anchor=v.get("anchor_ts", anchor),
                        src="claude", stale=stale, priority=v.get("priority", 2),
                        due=v.get("due", ""))
    elif status != "closed":
        item = dict(status=status, what=what, next="", anchor=anchor,
                    src="heuristic", stale=False, priority=3 if label == "personal" else 2)
    if not item: continue

    item.update(jid=jid, name=ch["name"], label=label,
                age_h=round((now - item.pop("anchor"))/3600, 1), meeting=meet,
                recent=recent_msgs(jid))
    if label == "personal": personal.append(item)
    else: (close_loop if item["status"] == "close_loop" else chase).append(item)

rank = lambda x: (x.get("priority", 2), 0 if x["src"] == "claude" else 1, -x["age_h"])
close_loop.sort(key=rank); chase.sort(key=rank)
personal.sort(key=rank)

since_last = []  # raw last-30-min peek: everything except ignore/clutter (FOMO killer)
for r in con.execute("""SELECT chat_jid, COUNT(*) n FROM messages
    WHERE ts > ? AND reaction_to_id IS NULL GROUP BY chat_jid ORDER BY MAX(ts) DESC""",
    (now - 1800,)):
    ch = chats.get(r["chat_jid"])
    if not ch or ch["label"] in ("ignore", "clutter"): continue
    nm = ch["name"]
    if nm.endswith("@s.whatsapp.net") or nm.endswith("@g.us"): continue
    since_last.append(dict(jid=r["chat_jid"], name=nm, label=ch["label"],
                           count=r["n"], recent=recent_msgs(r["chat_jid"], 3)))
    if len(since_last) >= 25: break

# Dropped balls: tracked chats silent 7-45d whose last exchange ended unresolved
dropped = []
tracked = set()
try:
    with open(os.path.join(BASE, "CHAT_MAP.csv")) as f:
        for row in csv.reader(l for l in f if not l.startswith("#")):
            if len(row) >= 2 and "@" in row[1]: tracked.add(row[1].strip())
except Exception: pass
queued = {x["jid"] for x in close_loop+chase+personal}
for r in con.execute("""SELECT chat_jid, MAX(ts) mts FROM messages
    WHERE reaction_to_id IS NULL AND revoked=0 GROUP BY chat_jid
    HAVING mts BETWEEN ? AND ?""", (now-45*86400, now-7*86400)):
    jid = r["chat_jid"]
    ch = chats.get(jid)
    if not ch or jid in queued: continue
    if ch["label"] not in ("dm","working-group"): continue
    if jid not in tracked and ch["label"] != "working-group": continue
    if ch["name"].endswith("@s.whatsapp.net") or ch["name"].endswith("@g.us"): continue
    v = state.get(jid)
    if v and v.get("status") in ("closed","snoozed") and (r["mts"] <= v.get("anchor_ts",0)): continue
    res = classify(jid, wdays=45, lenient=True)
    if not res or res[0] == "closed": continue
    st, what, anchor, meet = res
    dropped.append(dict(jid=jid, name=ch["name"], label=ch["label"], status=st,
        who_owes=("me" if st=="close_loop" else "them"), what=what,
        age_h=round((now-anchor)/3600,1), silent_d=round((now-r["mts"])/86400),
        meeting=meet, src="heuristic", stale=False, recent=recent_msgs(jid)))
dropped.sort(key=lambda x: x["silent_d"])

last_msg = con.execute("SELECT MAX(ts) FROM messages").fetchone()[0]
data = dict(
    generated=datetime.datetime.now(IST).strftime("%a %b %d, %Y · %H:%M IST"),
    generated_ts=now, last_msg_age_min=round((now - (last_msg or now))/60),
    last_intel=datetime.datetime.fromtimestamp(last_processed, IST).strftime("%b %d %H:%M") if last_processed else None,
    close_loop=close_loop[:20], chase=chase[:20], personal=personal[:10],
    since_last=since_last, dropped=dropped[:15],
)
with open(OUT, "w") as f:
    f.write("window.WA_AUTO = " + json.dumps(data, ensure_ascii=False) + ";\n")
con.close()
if __name__ == "__main__":
    print(f"close_loop={len(close_loop)} chase={len(chase)} personal={len(personal)} since={len(since_last)} dropped={len(dropped)}")

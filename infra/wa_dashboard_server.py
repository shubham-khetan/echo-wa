#!/usr/bin/env python3
"""Echo local server (127.0.0.1:8787, localhost only).
GET  /refresh  → re-run thread engine
GET  /search?q= → chat search for compose
GET  /intel    → copy intelligence prompt + open Claude
POST /send     → send via wacli (pauses sync daemon, restarts it)
POST /mute     → snooze a thread until new messages arrive; logs feedback
Background refresh every 15 min. Runs under launchd sh.echo.dashboard."""
import http.server, socketserver, subprocess, threading, time, os, sys, json, sqlite3
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(BASE, "infra", "wa_dashboard_refresh.py")
DB = os.path.join(BASE, "store", "wacli.db")
REL = os.path.join(BASE, "relevance_overrides.csv")
CLAUDE_DATA = os.path.join(BASE, "claude_data.js")
WACLI = "/opt/homebrew/bin/wacli"
PORT = 8787
UID = os.getuid()
send_lock = threading.Lock()

INTEL_PROMPT = ("Echo LEAN intelligence run — keep it quick, do NOT do a full sweep.\n"
    "Data lives in ~/.wacli-cos/ (use osascript+sqlite3/cat if file tools can't see it).\n"
    "1. Read STATE.json last_processed. Pull ONLY messages since then (osascript sqlite3 on store/wacli.db).\n"
    "2. For chats with new activity: update their entry in thread_state.json — flip status "
    "(close_loop / chase / closed), refresh what/next_action/anchor_ts. Add new real loops; "
    "close ack-only threads. Skip anything unchanged — do not re-verdict the whole board.\n"
    "3. Update claude_data.js drafts ONLY for items that changed. Keep drafts short.\n"
    "4. Set STATE.json last_processed = now. Run: curl -s http://127.0.0.1:8787/refresh\n"
    "SKIP: calendar cross-ref, dropped-ball deep scan, lexicon edits, ACTIVE_THREADS backfill, "
    "group sweeps — unless I explicitly ask. Finish with a 2-3 line delta (what changed). That's it.")

def run_refresh():
    try:
        r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, timeout=120)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)

def do_send(to, message):
    env = dict(os.environ, WACLI_STORE_DIR=os.path.join(BASE, "store"),
               PATH="/opt/homebrew/bin:" + os.environ.get("PATH", ""))
    with send_lock:
        subprocess.run(["launchctl", "bootout", "gui/%d/sh.echo.sync" % UID], capture_output=True)
        time.sleep(1.5)
        try:
            r = subprocess.run([WACLI, "send", "text", "--to", to, "--message", message,
                                "--post-send-wait", "3s", "--json"],
                               capture_output=True, text=True, timeout=90, env=env)
            ok, out = r.returncode == 0, (r.stdout + r.stderr)[-400:]
        except Exception as e:
            ok, out = False, str(e)
        finally:
            subprocess.run(["launchctl", "bootstrap", "gui/%d" % UID,
                            os.path.expanduser("~/Library/LaunchAgents/sh.echo.sync.plist")],
                           capture_output=True)
    return ok, out

def do_mute(jid, name):
    ts_path = os.path.join(BASE, "thread_state.json")
    state = json.load(open(ts_path)) if os.path.exists(ts_path) else {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    mx = con.execute("SELECT MAX(ts) FROM messages WHERE chat_jid=?", (jid,)).fetchone()[0] or 0
    con.close()
    prev = state.get(jid, {})
    state[jid] = dict(status="snoozed", who_owes=None, priority=prev.get("priority", 3),
                      what=prev.get("what", "muted by user from dashboard"),
                      next_action="", anchor_ts=mx, verdict_ts=int(time.time()),
                      source="user-mute")
    json.dump(state, open(ts_path, "w"), indent=2, ensure_ascii=False)
    with open(os.path.join(BASE, "feedback_log.csv"), "a") as f:
        f.write("%d,mute,%s,%s\n" % (int(time.time()), jid, name.replace(",", " ")))

def do_relevance(jid, name, relevant, priority, note):
    import csv
    rows = []
    if os.path.exists(REL):
        with open(REL) as f:
            rows = list(csv.DictReader(f))
    rows = [r for r in rows if r["jid"].strip() != jid]
    rows.append(dict(jid=jid, relevant=relevant, priority=priority or "normal",
                     note=note or ("toggled from dashboard: " + name)))
    with open(REL, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["jid","relevant","priority","note"])
        w.writeheader()
        w.writerows(rows)


def _read_claude_js():
    import re
    if not os.path.exists(CLAUDE_DATA): return None, None
    txt = open(CLAUDE_DATA).read()
    m = re.search(r"window\.WA_CLAUDE\s*=\s*(\{.*\});\s*$", txt, re.S)
    if not m: return None, None
    return json.loads(m.group(1)), txt

def _write_claude_js(obj):
    with open(CLAUDE_DATA, "w") as f:
        f.write("window.WA_CLAUDE = " + json.dumps(obj, ensure_ascii=False) + ";\n")

def do_flip(jid, name, new_status):
    ts_path = os.path.join(BASE, "thread_state.json")
    state = json.load(open(ts_path)) if os.path.exists(ts_path) else {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    mx = con.execute("SELECT MAX(ts) FROM messages WHERE chat_jid=?", (jid,)).fetchone()[0] or 0
    con.close()
    prev = state.get(jid, {})
    state[jid] = dict(status=new_status, who_owes=("me" if new_status=="close_loop" else "them"),
                      priority=prev.get("priority", 2), what=prev.get("what", "manually flipped by user"),
                      next_action=prev.get("next_action", ""), anchor_ts=mx,
                      verdict_ts=int(time.time()), source="user-flip")
    json.dump(state, open(ts_path, "w"), indent=2, ensure_ascii=False)

def do_dismiss_draft(jid, name):
    ts_path = os.path.join(BASE, "thread_state.json")
    state = json.load(open(ts_path)) if os.path.exists(ts_path) else {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    mx = con.execute("SELECT MAX(ts) FROM messages WHERE chat_jid=?", (jid,)).fetchone()[0] or 0
    con.close()
    prev = state.get(jid, {})
    state[jid] = dict(status="closed", who_owes=None, priority=prev.get("priority", 3),
                      what=prev.get("what", "manually dismissed by user"),
                      next_action="", anchor_ts=mx, verdict_ts=int(time.time()),
                      source="user-dismiss")
    json.dump(state, open(ts_path, "w"), indent=2, ensure_ascii=False)
    obj, _ = _read_claude_js()
    if obj:
        obj["drafts"] = [d for d in obj.get("drafts", []) if (d.get("jid") or "") != jid]
        _write_claude_js(obj)


def search_chats(q):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute("""SELECT jid, name, kind FROM chats
        WHERE kind IN ('dm','group') AND name LIKE ? ORDER BY last_message_ts DESC LIMIT 8""",
        ("%" + q + "%",)).fetchall()
    con.close()
    return [dict(jid=r[0], name=r[1], kind=r[2]) for r in rows]

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/refresh":
            ok, msg = run_refresh(); return self._json({"ok": ok, "msg": msg}, 200 if ok else 500)
        if u.path == "/search":
            q = parse_qs(u.query).get("q", [""])[0]
            return self._json({"results": search_chats(q) if len(q) >= 2 else []})
        if u.path == "/intel":
            subprocess.run("pbcopy", input=INTEL_PROMPT.encode())
            subprocess.run(["open", "-a", "Claude"], capture_output=True)
            return self._json({"ok": True})
        return super().do_GET()
    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n)) if n else {}
        except Exception as e:
            return self._json({"ok": False, "msg": str(e)}, 400)
        if u.path == "/mute":
            jid = (p.get("jid") or "").strip()
            if not jid: return self._json({"ok": False, "msg": "missing jid"}, 400)
            try:
                do_mute(jid, p.get("name", ""))
                run_refresh()
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "msg": str(e)}, 500)
        if u.path == "/relevance":
            jid = (p.get("jid") or "").strip()
            relevant = (p.get("relevant") or "").strip().lower()
            if not jid or relevant not in ("yes","no","archive"):
                return self._json({"ok": False, "msg": "missing/invalid jid or relevant"}, 400)
            try:
                do_relevance(jid, p.get("name",""), relevant, p.get("priority",""), p.get("note",""))
                run_refresh()
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "msg": str(e)}, 500)
        if u.path == "/flip":
            jid = (p.get("jid") or "").strip()
            new_status = (p.get("status") or "").strip()
            if not jid or new_status not in ("close_loop","chase"):
                return self._json({"ok": False, "msg": "missing/invalid jid or status"}, 400)
            try:
                do_flip(jid, p.get("name",""), new_status)
                run_refresh()
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "msg": str(e)}, 500)
        if u.path == "/dismiss-draft":
            jid = (p.get("jid") or "").strip()
            if not jid: return self._json({"ok": False, "msg": "missing jid"}, 400)
            try:
                do_dismiss_draft(jid, p.get("name",""))
                run_refresh()
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "msg": str(e)}, 500)
        if u.path == "/send":
            to, msg = (p.get("to") or "").strip(), (p.get("message") or "").strip()
            if not to or not msg: return self._json({"ok": False, "msg": "missing to/message"}, 400)
            ok, out = do_send(to, msg)
            if ok: run_refresh()
            return self._json({"ok": ok, "msg": out}, 200 if ok else 500)
        return self._json({"ok": False}, 404)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
    def log_message(self, *a): pass

def loop():
    while True:
        run_refresh()
        time.sleep(900)

threading.Thread(target=loop, daemon=True).start()
socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as srv:
    srv.serve_forever()

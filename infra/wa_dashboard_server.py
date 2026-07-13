#!/usr/bin/env python3
"""Echo local server (127.0.0.1:8787, localhost only).
GET  /refresh  → re-run thread engine
GET  /search?q= → chat search for compose
GET  /intel    → copy intelligence prompt + open Claude
POST /send     → send via wacli (pauses sync daemon, restarts it)
POST /mute     → snooze a thread until new messages arrive; logs feedback
Background refresh every 15 min. Runs under launchd sh.wacli.dashboard."""
import http.server, socketserver, subprocess, threading, time, os, sys, json, sqlite3
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(BASE, "infra", "wa_dashboard_refresh.py")
DB = os.path.join(BASE, "store", "wacli.db")
WACLI = "/opt/homebrew/bin/wacli"
PORT = 8787
UID = os.getuid()
send_lock = threading.Lock()

INTEL_PROMPT = ("WhatsApp intelligence run. FIRST: if file tools cannot see a path below, read it "
                "via osascript (do shell script cat …) — never conclude a file is missing. "
                "Follow /Users/shubham/Documents/Claude/Projects/Master Project/skills/whatsapp-intelligence/"
                "SKILL.md end to end: re-verdict both queues (window context, calendar cross-ref "
                "on meeting-flagged threads), triage the dropped-balls queue, respect user-mute "
                "feedback in feedback_log.csv, update thread_state.json + claude_data.js + "
                "heuristics_config.json lexicons, backfill conclusions into ACTIVE_THREADS, "
                "advance STATE.json last_processed, then report the delta.")

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
        subprocess.run(["launchctl", "bootout", "gui/%d/sh.wacli.sync" % UID], capture_output=True)
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
                            os.path.expanduser("~/Library/LaunchAgents/sh.wacli.sync.plist")],
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

def _max_ts():
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        v = con.execute("SELECT MAX(ts) FROM messages").fetchone()[0] or 0
        con.close(); return v
    except Exception: return 0

def loop():
    # Refresh on new activity (incl. messages you send from your phone) within ~60s,
    # and a hard refresh at least every 15 min as a floor.
    run_refresh()
    last_seen = _max_ts(); last_full = time.time()
    while True:
        time.sleep(60)
        cur = _max_ts()
        if cur > last_seen or (time.time() - last_full) >= 900:
            run_refresh(); last_seen = cur; last_full = time.time()

threading.Thread(target=loop, daemon=True).start()
socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as srv:
    srv.serve_forever()

#!/bin/bash
# Echo installer — macOS. Local WhatsApp mirror + loop dashboard.
set -e
ECHO_DIR="$HOME/.echo"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "── Echo install ──"
command -v brew >/dev/null || { echo "Homebrew required: https://brew.sh"; exit 1; }
command -v wacli >/dev/null || { echo "Installing wacli…"; brew install openclaw/tap/wacli; }

mkdir -p "$ECHO_DIR/store" "$ECHO_DIR/infra" "$ECHO_DIR/digests"
cp "$REPO_DIR/infra/wa_dashboard_refresh.py" "$REPO_DIR/infra/wa_dashboard_server.py" "$ECHO_DIR/infra/"
cp "$REPO_DIR/WHATSAPP_DASHBOARD.html" "$ECHO_DIR/"
[ -f "$ECHO_DIR/heuristics_config.json" ] || cp "$REPO_DIR/heuristics_config.json" "$ECHO_DIR/"
[ -f "$ECHO_DIR/label_overrides.csv" ]   || echo "jid,label,note" > "$ECHO_DIR/label_overrides.csv"
[ -f "$ECHO_DIR/CHAT_MAP.csv" ]          || echo "name,jid,kind,slug" > "$ECHO_DIR/CHAT_MAP.csv"
[ -f "$ECHO_DIR/thread_state.json" ]     || echo "{}" > "$ECHO_DIR/thread_state.json"
[ -f "$ECHO_DIR/STATE.json" ]            || echo '{"last_processed": null, "last_group_sweep": null}' > "$ECHO_DIR/STATE.json"
echo "window.WA_CLAUDE={updated:null,drafts:[],commitments:[],group_notes:'Run bootstrap (see README) to configure.'};" > "$ECHO_DIR/claude_data.js"
cp -r "$REPO_DIR/skills" "$ECHO_DIR/" 2>/dev/null || true

# launchd agents (generated with this user's paths)
for tpl in sync dashboard; do
  P="$HOME/Library/LaunchAgents/sh.echo.$tpl.plist"
  if [ "$tpl" = "sync" ]; then
    PROG="<string>$(command -v wacli)</string><string>sync</string><string>--follow</string>"
    ENVV="<key>EnvironmentVariables</key><dict><key>WACLI_STORE_DIR</key><string>$ECHO_DIR/store</string><key>WACLI_SYNC_MAX_DB_SIZE</key><string>2GB</string></dict>"
  else
    PROG="<string>/usr/bin/python3</string><string>$ECHO_DIR/infra/wa_dashboard_server.py</string>"
    ENVV=""
  fi
  cat > "$P" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>sh.echo.$tpl</string>
<key>ProgramArguments</key><array>$PROG</array>$ENVV
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>ProcessType</key><string>Background</string>
<key>StandardErrorPath</key><string>$ECHO_DIR/store/$tpl.err.log</string>
</dict></plist>
PLIST
done

echo
echo "── Pair with WhatsApp: scan the QR from your phone (Settings → Linked devices) ──"
WACLI_STORE_DIR="$ECHO_DIR/store" WACLI_DEVICE_LABEL="Echo local mirror" wacli auth

echo "── Starting daemons ──"
for tpl in sync dashboard; do
  launchctl bootout "gui/$(id -u)/sh.echo.$tpl" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/sh.echo.$tpl.plist"
done
sleep 3
open "http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html" || true
echo
echo "✅ Echo is live. Next: open Claude Code in this repo and say: bootstrap echo"
echo "   (backfill older history anytime: WACLI_STORE_DIR=$ECHO_DIR/store wacli history backfill --chat <jid>)"

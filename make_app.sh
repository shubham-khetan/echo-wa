#!/bin/bash
# Build /Applications/Echo.app — a thin launcher that opens Echo in a chromeless
# Chrome/Brave app-window (own dock icon + isolated profile). Avoids WKWebView's
# ScreenTime localhost shield, so send/search/mute work exactly like the browser.
set -e
APP='/Applications/Echo.app'
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" << 'P'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>Echo</string>
<key>CFBundleIdentifier</key><string>sh.echo.app</string><key>CFBundleExecutable</key><string>echo</string>
<key>CFBundleIconFile</key><string>icon</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>
P
cat > "$APP/Contents/MacOS/echo" << 'S'
#!/bin/bash
URL='http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html'
PROFILE="$HOME/.echo/.chrome-echo"

# The Echo window is a plain "Google Chrome" process under the hood (macOS has
# no separate "Echo" app identity for it once spawned). Re-invoking this
# launcher while it's already running does NOT reactivate the existing window
# -- exec'''ing a fresh Chrome --app invocation can get misrouted by macOS/Chrome'''s
# single-instance IPC into the ALREADY-RUNNING DEFAULT Chrome profile instead,
# opening a stray new tab there. Fix: if the dedicated Echo Chrome process is
# already alive (found via its unique --user-data-dir), bring THAT process
# forward by PID via System Events instead of launching anything new.
PID=$(pgrep -f -- "--user-data-dir=$PROFILE" | head -1)
if [ -n "$PID" ]; then
  osascript -e "tell application \"System Events\" to set frontmost of (first process whose unix id is $PID) to true" > /dev/null 2>&1
  exit 0
fi

if [ -d '/Applications/Google Chrome.app' ]; then
  exec '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --app="$URL" --user-data-dir="$PROFILE" --class=Echo
elif [ -d '/Applications/Brave Browser.app' ]; then
  exec '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' --app="$URL" --user-data-dir="$PROFILE"
else
  exec open "$URL"
fi
S
chmod +x "$APP/Contents/MacOS/echo"
python3 - << 'PY' || echo 'icon skipped (pip install pillow for the icon)'
from PIL import Image, ImageDraw
import math, os, subprocess
S=1024; img=Image.new('RGBA',(S,S),(0,0,0,0)); d=ImageDraw.Draw(img)
d.rounded_rectangle([64,64,S-64,S-64],radius=230,fill=(22,25,32,255))
d.arc([262,262,S-262,S-262],start=80,end=10,fill=(245,245,247,255),width=64)
a=math.radians(45); r=(S-524)/2; x,y=S/2+r*math.cos(a),S/2+r*math.sin(a)
d.ellipse([x-86,y-86,x+86,y+86],fill=(37,211,102,255))
os.makedirs('/tmp/echo.iconset',exist_ok=True)
for z in (16,32,64,128,256,512,1024):
    img.resize((z,z)).save(f'/tmp/echo.iconset/icon_{z}x{z}.png')
    if z<1024: img.resize((z*2,z*2)).save(f'/tmp/echo.iconset/icon_{z}x{z}@2x.png')
subprocess.run(['iconutil','-c','icns','/tmp/echo.iconset','-o','/Applications/Echo.app/Contents/Resources/icon.icns'],check=True)
PY
codesign --force --deep -s - "$APP" 2>/dev/null || true
echo 'Echo.app installed - find it in Spotlight, drag to Dock.'

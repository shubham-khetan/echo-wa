#!/bin/bash
# Optional: create /Applications/Echo.app (Dock + Spotlight launcher)
set -e
APP='/Applications/Echo.app'
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" << 'P'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>Echo</string>
<key>CFBundleIdentifier</key><string>sh.echo.app</string><key>CFBundleExecutable</key><string>echo</string>
<key>CFBundleIconFile</key><string>icon</string><key>CFBundlePackageType</key><string>APPL</string><key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict></dict></plist>
P
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
if command -v swiftc >/dev/null; then
  echo 'Compiling native wrapper (dock indicator, real quit)…'
  swiftc -O "$REPO_DIR/infra/echo_app.swift" -o "$APP/Contents/MacOS/echo" -framework Cocoa -framework WebKit
else
  cat > "$APP/Contents/MacOS/echo" << 'S'
#!/bin/bash
URL='http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html'
[ -d '/Applications/Google Chrome.app' ] && exec open -na 'Google Chrome' --args --app="$URL" || exec open "$URL"
S
  chmod +x "$APP/Contents/MacOS/echo"
fi
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
echo '✅ Echo.app installed — find it in Spotlight, drag to Dock.'

import Cocoa
import WebKit

class Bridge: NSObject, WKScriptMessageHandler {
    weak var web: WKWebView?
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let body = m.body as? [String: Any],
              let path = body["path"] as? String,
              let cbid = body["cbid"] as? String else { return }
        let method = (body["method"] as? String) ?? "GET"
        var req = URLRequest(url: URL(string: "http://127.0.0.1:8787" + path)!)
        req.httpMethod = method
        if let payload = body["payload"] as? String, method == "POST" {
            req.httpBody = payload.data(using: .utf8)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        req.timeoutInterval = 120
        URLSession.shared.dataTask(with: req) { data, _, err in
            let ok = err == nil
            let txt = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let b64 = txt.data(using: .utf8)!.base64EncodedString()
            let js = "window.__echoBridgeResolve('\(cbid)', \(ok), '\(b64)')"
            DispatchQueue.main.async { self.web?.evaluateJavaScript(js, completionHandler: nil) }
        }.resume()
    }
}

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let bridge = Bridge()
    func applicationDidFinishLaunching(_ n: Notification) {
        let rect = NSRect(x: 0, y: 0, width: 960, height: 860)
        window = NSWindow(contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Echo"; window.center(); window.setFrameAutosaveName("EchoMain"); window.delegate = self
        let cfg = WKWebViewConfiguration()
        let ucc = WKUserContentController()
        ucc.add(bridge, name: "echo")
        // flag the page that it's inside the native app + provide the bridge shim
        let shim = """
        window.__ECHO_NATIVE = true;
        window.__echoCbs = {};
        window.__echoBridgeResolve = function(id, ok, b64){
          var cb = window.__echoCbs[id]; if(!cb) return; delete window.__echoCbs[id];
          var txt = ok ? decodeURIComponent(escape(atob(b64))) : '';
          cb(ok, txt);
        };
        window.echoFetch = function(path, method, payload){
          return new Promise(function(res, rej){
            var id = 'cb'+Math.random().toString(36).slice(2);
            window.__echoCbs[id] = function(ok, txt){
              if(!ok){ rej(new Error('bridge failed')); return; }
              try{ res(JSON.parse(txt)); }catch(e){ res({}); }
            };
            window.webkit.messageHandlers.echo.postMessage({path:path, method:method||'GET', payload:payload||'', cbid:id});
          });
        };
        """
        ucc.addUserScript(WKUserScript(source: shim, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        cfg.userContentController = ucc
        let web = WKWebView(frame: rect, configuration: cfg)
        web.autoresizingMask = [.width, .height]
        bridge.web = web
        window.contentView = web
        web.load(URLRequest(url: URL(string: "http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html")!))
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows v: Bool) -> Bool {
        if !v { window.makeKeyAndOrderFront(nil) }; return true
    }
}
let app = NSApplication.shared
let d = AppDelegate()
app.delegate = d
app.setActivationPolicy(.regular)
app.run()

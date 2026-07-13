import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    func applicationDidFinishLaunching(_ n: Notification) {
        let rect = NSRect(x: 0, y: 0, width: 960, height: 860)
        window = NSWindow(contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Echo"
        window.center()
        window.setFrameAutosaveName("EchoMain")
        window.delegate = self
        let web = WKWebView(frame: rect)
        web.autoresizingMask = [.width, .height]
        window.contentView = web
        web.load(URLRequest(url: URL(string: "http://127.0.0.1:8787/WHATSAPP_DASHBOARD.html")!))
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { window.makeKeyAndOrderFront(nil) }
        return true
    }
}
let app = NSApplication.shared
let d = AppDelegate()
app.delegate = d
app.setActivationPolicy(.regular)
app.run()

import AppKit
import SwiftUI

/// Shared native chrome and full-screen eligibility for Baton windows.
public enum BatonWindowConfiguration {
    /// Configures both the ordinary SwiftUI window and the fixture review window.
    @MainActor public static func apply(to window: NSWindow) {
        apply(to: window, theme: .graphite)
    }
    @MainActor public static func apply(to window: NSWindow, theme: Theme) {
        let controls: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]
        if !window.styleMask.isSuperset(of: controls) { window.styleMask.formUnion(controls) }
        var behavior = window.collectionBehavior
        behavior.subtract([.fullScreenAuxiliary, .fullScreenNone])
        behavior.insert(.fullScreenPrimary)
        if behavior != window.collectionBehavior { window.collectionBehavior = behavior }
        let minimum = NSSize(width: 1000, height: 600)
        if window.contentMinSize != minimum { window.contentMinSize = minimum }
        applyGlass(to: window, theme: theme)
    }
    /// Avoids relayout on ordinary SwiftUI updates and preserves AppKit's full-screen state.
    @MainActor public static func applyGlass(to window: NSWindow, theme: Theme) {
        if !window.titlebarAppearsTransparent { window.titlebarAppearsTransparent = true }
        if window.titleVisibility != .hidden { window.titleVisibility = .hidden }
        if !window.styleMask.contains(.fullSizeContentView) { window.styleMask.insert(.fullSizeContentView) }
        let color = NSColor(theme.background)
        if window.backgroundColor != color { window.backgroundColor = color }
        let appearance: NSAppearance.Name = theme == .graphite ? .darkAqua : .aqua
        if window.appearance?.name != appearance { window.appearance = NSAppearance(named: appearance) }
    }
}

/// Owns one main window across launch, menu-bar actions and reopening after close.
@MainActor public final class BatonMainWindowController: NSWindowController {
    public let model: WindowViewModel
    public init(model: WindowViewModel) {
        self.model = model
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        BatonWindowConfiguration.apply(to: window)
        window.title = "Baton"
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: WindowView(model: model).task { await model.refresh() })
        window.center()
        super.init(window: window)
    }
    public required init?(coder: NSCoder) { nil }
    public override func showWindow(_ sender: Any?) {
        if let window, window.isMiniaturized { window.deminiaturize(sender) }
        super.showWindow(sender)
        window?.makeKeyAndOrderFront(sender)
    }
}

/// Applies the same glass chrome to windows created by SwiftUI and by the fixture launcher.
struct WindowGlassChrome: NSViewRepresentable {
    let theme: Theme
    func makeNSView(context: Context) -> ChromeProbe { ChromeProbe(theme: theme) }
    func updateNSView(_ view: ChromeProbe, context: Context) {
        view.theme = theme; view.configure()
    }
    final class ChromeProbe: NSView {
        var theme: Theme
        init(theme: Theme) { self.theme = theme; super.init(frame: .zero) }
        required init?(coder: NSCoder) { nil }
        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); configure() }
        func configure() {
            guard let window else { return }
            BatonWindowConfiguration.apply(to: window, theme: theme)
        }
    }
}

/// ImageRenderer omits native scrolling; snapshots lay out the same content directly.
private struct SnapshotPresentationKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var batonSnapshotPresentation: Bool {
        get { self[SnapshotPresentationKey.self] }
        set { self[SnapshotPresentationKey.self] = newValue }
    }
}

/// Uses native overlay thumbs without a solid track cutting through the glass panels.
struct WindowScrollArea<Content: View>: View {
    @Environment(\.batonSnapshotPresentation) private var snapshot
    private let axes: Axis.Set
    private let snapshotClips: Bool
    private let content: Content
    init(_ axes: Axis.Set = .vertical, snapshotClips: Bool = true, @ViewBuilder content: () -> Content) {
        self.axes = axes; self.snapshotClips = snapshotClips; self.content = content()
    }
    var body: some View {
        Group {
            if snapshot && !snapshotClips { insetContent }
            else if snapshot {
                GeometryReader { geometry in
                    insetContent.frame(width: geometry.size.width, alignment: .topLeading)
                        .frame(height: geometry.size.height, alignment: .topLeading).clipped()
                }
            } else {
                ScrollView(axes) {
                    insetContent.background(OverlayScrollConfiguration())
                }.scrollIndicatorsFlash(onAppear: true)
            }
        }
    }
    private var insetContent: some View {
        content.padding(.trailing, axes.contains(.vertical) ? 12 : 0)
            .padding(.bottom, axes.contains(.horizontal) ? 12 : 0)
    }
}

/// Configures only the enclosing Baton scroll view; native dragging and accessibility remain intact.
struct OverlayScrollConfiguration: NSViewRepresentable {
    func makeNSView(context: Context) -> ScrollProbe { ScrollProbe() }
    func updateNSView(_ view: ScrollProbe, context: Context) { view.configure() }

    final class ScrollProbe: NSView {
        override func viewDidMoveToSuperview() { super.viewDidMoveToSuperview(); configure() }
        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); configure() }
        func configure() {
            // SwiftUI can attach the content to its clip view after this update.
            DispatchQueue.main.async { [weak self] in
                guard let scroll = self?.enclosingScrollView else { return }
                scroll.scrollerStyle = .overlay
                scroll.drawsBackground = false
            }
        }
    }
}

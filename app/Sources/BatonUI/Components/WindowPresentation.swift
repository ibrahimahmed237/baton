import AppKit
import SwiftUI

/// Gives the fixture review window the same resize and full-screen affordances as the app scene.
public enum BatonWindowConfiguration {
    /// Preserves standard window controls and allows expansion beyond the initial content size.
    @MainActor public static func apply(to window: NSWindow) {
        window.styleMask.insert(.resizable)
        window.collectionBehavior.insert(.fullScreenPrimary)
        window.contentMinSize = NSSize(width: 1000, height: 600)
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

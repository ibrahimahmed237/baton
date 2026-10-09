import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

@Suite(.serialized)
struct WindowInteractionTests {
    @MainActor @Test func reviewWindowAllowsResizeAndFullScreen() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        BatonWindowConfiguration.apply(to: window)
        #expect(window.styleMask.contains(.resizable))
        #expect(window.collectionBehavior.contains(.fullScreenPrimary))
        #expect(window.contentMinSize == NSSize(width: 1000, height: 600))
        window.setContentSize(NSSize(width: 1400, height: 900))
        #expect(window.contentView?.bounds.size == NSSize(width: 1400, height: 900))
        window.close()
    }

    @MainActor @Test func ordinaryWindowProbeEnablesNativeFullScreen() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let probe = WindowGlassChrome.ChromeProbe(theme: .light)
        window.contentView?.addSubview(probe)
        for conflict in [NSWindow.CollectionBehavior.fullScreenAuxiliary, .fullScreenNone] {
            window.collectionBehavior = [conflict, .moveToActiveSpace]
            probe.configure()
            #expect(window.collectionBehavior.contains(.fullScreenPrimary))
            #expect(!window.collectionBehavior.contains(.fullScreenAuxiliary))
            #expect(!window.collectionBehavior.contains(.fullScreenNone))
            #expect(window.collectionBehavior.contains(.moveToActiveSpace))
            #expect(window.contentMinSize == NSSize(width: 1000, height: 600))
        }
        window.close()
    }

    @MainActor @Test func repeatedChromeUpdatesDoNotResetWindowStyleOrFrame() {
        let window = StyleCountingWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                                         styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let probe = WindowGlassChrome.ChromeProbe(theme: .light)
        window.contentView?.addSubview(probe)
        window.setContentSize(NSSize(width: 1400, height: 900))
        let frame = window.frame
        let assignments = window.styleAssignments
        for _ in 0..<20 { probe.configure() }
        #expect(window.styleAssignments == assignments)
        #expect(window.frame == frame)
        #expect(window.appearance?.name == .aqua)
        window.close()
    }

    @MainActor @Test func mainWindowRetainsStandardControlsAndReopensTheSameContent() async throws {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh()
        let controller = BatonMainWindowController(model: model)
        let window = try #require(controller.window)
        // Native behavior is exercised off screen; no other application's windows are touched.
        window.setFrameOrigin(NSPoint(x: -10000, y: -10000))
        #expect(window.styleMask.isSuperset(of: [.titled, .closable, .miniaturizable, .resizable]))
        for control in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
            let button = try #require(window.standardWindowButton(control))
            #expect(!button.isHidden)
            #expect(button.isEnabled)
        }
        #expect(window.collectionBehavior.contains(.fullScreenPrimary))
        controller.showWindow(nil)
        #expect(window.isVisible)
        let content = window.contentView
        model.navigate(to: .suggestions)
        window.close()
        #expect(!window.isVisible)
        controller.showWindow(nil)
        #expect(controller.window === window)
        #expect(window.contentView === content)
        #expect(controller.model === model)
        #expect(model.section == .suggestions)
        #expect(window.isVisible)
        window.close()
    }

    @MainActor @Test func titleBarUsesTheAppPaletteAndRetainsNativeControls() throws {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        for theme in Theme.allCases {
            BatonWindowConfiguration.applyGlass(to: window, theme: theme)
            #expect(window.titlebarAppearsTransparent)
            #expect(window.titleVisibility == .hidden)
            #expect(window.styleMask.contains(.fullSizeContentView))
            #expect(window.backgroundColor == NSColor(theme.background))
            #expect(window.appearance?.name == (theme == .graphite ? .darkAqua : .aqua))
            #expect(window.standardWindowButton(.closeButton) != nil)
            #expect(window.standardWindowButton(.miniaturizeButton) != nil)
            #expect(window.standardWindowButton(.zoomButton) != nil)
            #expect(window.contentLayoutRect.height < window.contentView!.bounds.height)
        }
        window.close()
    }

    @MainActor @Test func swiftUIWindowChromeUpdatesWhenTheThemeChanges() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let probe = WindowGlassChrome.ChromeProbe(theme: .light)
        window.contentView?.addSubview(probe)
        #expect(window.titlebarAppearsTransparent)
        #expect(window.appearance?.name == .aqua)
        probe.theme = .graphite; probe.configure()
        #expect(window.appearance?.name == .darkAqua)
        #expect(window.backgroundColor == NSColor(Theme.graphite.background))
        window.close()
    }

    @MainActor @Test func glassWindowMinimumSizeFitsHostedContent() async {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh()
        let host = NSHostingView(rootView: WindowView(model: model))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        BatonWindowConfiguration.apply(to: window)
        window.contentView = host
        window.setContentSize(window.contentMinSize)
        host.layoutSubtreeIfNeeded()
        try? await Task.sleep(for: .milliseconds(40))
        #expect(host.fittingSize.height <= host.bounds.height)
        #expect(host.fittingSize.width <= host.bounds.width)
        window.close()
    }

    @MainActor @Test func repeatedSidebarClickPreservesTheSelectedChat() async {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh()
        for section in model.sections {
            model.navigate(to: section)
            let selection: WindowSelection
            switch section {
            case .linked, .attention: selection = .link(model.listedLinks[0].linkID)
            case .suggestions: selection = model.suggestionSelection(model.suggestions[0])
            case .chats(let tool): selection = .chat(tool, model.chats[tool]![0].id)
            case .activity: selection = .event(model.activity[0].link.linkID, model.activity[0].event.id)
            }
            model.select(selection)
            model.navigate(to: section)
            #expect(model.selection == selection)
        }
    }

    @MainActor @Test func expandedWindowUsesTheAvailableSpaceInBothThemes() async throws {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh(); model.select(.link(3))
        let status = model.makeStatusModel(); await status.load(link: 3)
        for theme in Theme.allCases {
            for size in [CGSize(width: 1000, height: 600), CGSize(width: 1400, height: 900)] {
                let renderer = ImageRenderer(content: WindowView(model: model, statusModel: status).batonTheme(theme)
                    .environment(\.batonSnapshotPresentation, true))
                renderer.proposedSize = ProposedViewSize(size)
                let image = try #require(renderer.nsImage)
                #expect(image.size == size)
                let tiff = try #require(image.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:]))
                try png.write(to: ComponentTests.root.appendingPathComponent("Snapshots/UI1-window-\(Int(size.width))-\(theme.rawValue).png"))
            }
        }
    }

    @MainActor @Test func sidebarBlankAreaRespondsToOneClick() async throws {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh()
        let host = NSHostingView(rootView: WindowView(model: model))
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 1000, height: 600),
                              styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.makeKeyAndOrderFront(nil)
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(60))
        // The right-hand blank space of the third sidebar row, beyond its text.
        let location = NSPoint(x: 180, y: window.contentLayoutRect.maxY - 116)
        for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
            let event = try #require(NSEvent.mouseEvent(with: type, location: location, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                context: nil, eventNumber: 1, clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0))
            window.sendEvent(event)
        }
        try await Task.sleep(for: .milliseconds(20))
        #expect(model.section == .suggestions)
        window.close()
    }

    @MainActor @Test func longDialogCanScrollToItsFinalActions() async throws {
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_unavailable")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        let model = LinkDialogViewModel(engine: fixture); await model.load(source: source)
        let host = NSHostingView(rootView: LinkDialogView(model: model))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 650, height: 560),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(60))
        func scrollViews(_ view: NSView) -> [NSScrollView] {
            (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(scrollViews)
        }
        let scroll = try #require(scrollViews(host).first)
        let document = try #require(scroll.documentView)
        #expect(document.bounds.height > scroll.contentView.bounds.height)
        scroll.contentView.scroll(to: NSPoint(x: 0, y: document.bounds.maxY - scroll.contentView.bounds.height))
        scroll.reflectScrolledClipView(scroll.contentView)
        #expect(abs(scroll.contentView.bounds.maxY - document.bounds.maxY) < 1)
        window.close()
    }

    @MainActor @Test func repeatedTurnJumpIssuesANewScrollRequest() async throws {
        let model = SyncStatusViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d4_s1"))
        await model.load(link: 3)
        let turn = try #require(model.turns.first?.id)
        model.jump(to: turn)
        let first = model.focusRequest
        model.jump(to: turn)
        #expect(model.focusRequest == first + 1)
        #expect(model.focusedTurn == turn)
        model.jump(to: -1)
        #expect(model.focusRequest == first + 1)
    }

    @MainActor @Test func liveSwiftUIScrollHostUsesOverlayAndKeepsOverflow() async throws {
        let host = NSHostingView(rootView: WindowScrollArea {
            VStack { ForEach(0..<100) { Text($0, format: .number).frame(height: 30) } }
        }.frame(width: 300, height: 200))
        host.frame = NSRect(x: 0, y: 0, width: 300, height: 200)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(60))
        func scrollViews(_ view: NSView) -> [NSScrollView] {
            (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(scrollViews)
        }
        let scroll = try #require(scrollViews(host).first)
        #expect(scroll.scrollerStyle == .overlay)
        #expect(!scroll.drawsBackground)
        #expect(scroll.documentView!.frame.height > scroll.contentView.bounds.height)
        let before = scroll.contentView.bounds.origin
        scroll.contentView.scroll(to: NSPoint(x: 0, y: 500))
        scroll.reflectScrolledClipView(scroll.contentView)
        #expect(scroll.contentView.bounds.origin != before)
        window.close()
    }

    @MainActor @Test func overlayProbeConfiguresOnlyItsEnclosingScrollView() async {
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 300, height: 200))
        scroll.hasVerticalScroller = true
        scroll.scrollerStyle = .legacy
        scroll.drawsBackground = true
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 1000))
        scroll.documentView = content
        let probe = OverlayScrollConfiguration.ScrollProbe()
        content.addSubview(probe)
        probe.configure()
        // Allow the attachment callback to run, without requiring a visible desktop window.
        try? await Task.sleep(for: .milliseconds(20))
        #expect(scroll.scrollerStyle == .overlay)
        #expect(!scroll.drawsBackground)
        #expect(scroll.hasVerticalScroller)
        #expect(scroll.documentView === content)
    }
}

@MainActor private final class StyleCountingWindow: NSWindow {
    var styleAssignments = 0
    override var styleMask: NSWindow.StyleMask {
        didSet { styleAssignments += 1 }
    }
}

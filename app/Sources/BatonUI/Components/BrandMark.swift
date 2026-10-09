import AppKit
import SwiftUI

/// Different surroundings for content, the system menu and the Dock.
public enum BrandPlacement: Sendable { case content, menu, dock }

/// Supplies the signed burgundy-and-black identity bundled with BatonUI.
public enum BatonBrand {
    /// Loads the transparent handoff mark and I.A signature without a baked-in tile.
    public static func nativeIcon() -> NSImage? {
        guard let url = Bundle.module.url(forResource: "baton-mark", withExtension: "png", subdirectory: "Brand") else { return nil }
        return NSImage(contentsOf: url)
    }

    /// Renders the Dock identity on its white tile in either appearance.
    @MainActor public static func applicationIcon(theme: Theme, reduceTransparency: Bool? = nil) -> NSImage? {
        let renderer = ImageRenderer(content: BrandMark(size: 256, reduceTransparency: reduceTransparency, placement: .dock).batonTheme(.light))
        renderer.scale = 2
        return renderer.nsImage
    }
}

/// Keeps the mark colors unchanged and chooses only the surrounding surface.
public struct BrandMark: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.accessibilityReduceTransparency) private var systemReduceTransparency
    private let placement: BrandPlacement
    private let size: CGFloat
    private let reduceTransparencyOverride: Bool?

    /// Creates the signed logo at a size appropriate to its surrounding content.
    public init(size: CGFloat = 96, reduceTransparency: Bool? = nil, placement: BrandPlacement = .content) {
        self.placement = placement
        self.size = size; self.reduceTransparencyOverride = reduceTransparency
    }

    public var body: some View {
        Group {
            if let icon = BatonBrand.nativeIcon() {
                Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
            }
        }
        .frame(width: placement == .dock ? size * 0.82 : size, height: placement == .dock ? size * 0.82 : size)
        .frame(width: size, height: size)
        .background {
            if placement == .dock {
                RoundedRectangle(cornerRadius: size * 0.22).fill(Color.white)
            } else if placement == .menu, theme == .graphite {
                RoundedRectangle(cornerRadius: size * 0.18)
                    .fill(LinearGradient(colors: [Color(white: 0.76), Color(white: 0.57)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                    .opacity((reduceTransparencyOverride ?? systemReduceTransparency) ? 1 : 0.9)
                    .overlay {
                        RoundedRectangle(cornerRadius: size * 0.18)
                            .strokeBorder(Color.white.opacity(0.24), lineWidth: size < 30 ? 0.5 : 1)
                    }
            }
        }
        .accessibilityHidden(true)
    }
}

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
    private let placement: BrandPlacement
    private let size: CGFloat

    /// Creates the signed logo at a size appropriate to its surrounding content.
    public init(size: CGFloat = 96, reduceTransparency: Bool? = nil, placement: BrandPlacement = .content) {
        self.placement = placement
        self.size = size
    }

    public var body: some View {
        Group {
            if let icon = BatonBrand.nativeIcon() {
                ZStack {
                    if placement == .menu {
                        // Outline the silhouette behind the original pixels, not the artwork itself.
                        ForEach(0..<8) { step in
                            Image(nsImage: icon).resizable().renderingMode(.template).scaledToFit()
                                .foregroundStyle(.white)
                                .offset(x: cos(Double(step) * .pi / 4) * 0.6,
                                        y: sin(Double(step) * .pi / 4) * 0.6)
                        }
                    }
                    Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
                }
            }
        }
        .frame(width: placement == .dock ? size * 0.98 : size, height: placement == .dock ? size * 0.98 : size)
        .frame(width: size, height: size)
        .background {
            if placement == .dock {
                RoundedRectangle(cornerRadius: size * 0.22).fill(Color.white)

            }
        }
        .accessibilityHidden(true)
    }
}

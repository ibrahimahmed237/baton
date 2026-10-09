import AppKit
import SwiftUI

/// Different surroundings for content, the system menu and the Dock.
public enum BrandPlacement: Sendable { case content, menu, dock }

/// Supplies the signed burgundy-and-black identity bundled with BatonUI.
public enum BatonBrand {
    /// Loads the transparent handoff mark and I.A signature without a baked-in tile.
    @MainActor public static func nativeIcon() -> NSImage? { sourceIcon }

    @MainActor private static let sourceIcon: NSImage? = {
        guard let url = Bundle.module.url(forResource: "baton-mark", withExtension: "png", subdirectory: "Brand") else { return nil }
        return NSImage(contentsOf: url)
    }()

    @MainActor fileprivate static let compactIcon: NSImage? = {
        guard let icon = sourceIcon else { return nil }
        return croppedIcon(from: icon) ?? icon
    }()

    /// Removes transparent canvas around the complete signed artwork at compact sizes.
    fileprivate static func croppedIcon(from image: NSImage) -> NSImage? {
        var proposed = NSRect(origin: .zero, size: image.size)
        guard let source = image.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else { return nil }
        guard let providerData = source.dataProvider?.data,
              let bytes = CFDataGetBytePtr(providerData) else { return nil }
        let bytesPerPixel = source.bitsPerPixel / 8
        guard bytesPerPixel > 0 else { return nil }
        let alphaOffset: Int
        switch source.alphaInfo {
        case .first, .premultipliedFirst, .noneSkipFirst: alphaOffset = 0
        case .last, .premultipliedLast, .noneSkipLast: alphaOffset = bytesPerPixel - 1
        default: return nil
        }
        var minX = source.width; var minY = source.height
        var maxX = -1; var maxY = -1
        for y in 0..<source.height {
            for x in 0..<source.width {
                let alpha = bytes[y * source.bytesPerRow + x * bytesPerPixel + alphaOffset]
                guard alpha > 5 else { continue }
                minX = min(minX, x); minY = min(minY, y)
                maxX = max(maxX, x); maxY = max(maxY, y)
            }
        }
        guard maxX >= minX, maxY >= minY else { return nil }
        let padding = Int(Double(max(source.width, source.height)) * 0.02) + 2
        let left = max(0, minX - padding); let top = max(0, minY - padding)
        let right = min(source.width, maxX + padding + 1)
        let bottom = min(source.height, maxY + padding + 1)
        let rect = CGRect(x: left, y: top, width: right - left, height: bottom - top)
        guard let cropped = source.cropping(to: rect) else { return nil }
        return NSImage(cgImage: cropped, size: NSSize(width: cropped.width, height: cropped.height))
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
            if let displayedIcon = placement == .content ? BatonBrand.nativeIcon() : BatonBrand.compactIcon {
                ZStack {
                    if placement == .menu {
                        Image(nsImage: displayedIcon).resizable().interpolation(.high).renderingMode(.template).scaledToFit()
                            .foregroundStyle(theme.menuGlass)
                    } else {
                        Image(nsImage: displayedIcon).resizable().interpolation(.high).scaledToFit()
                    }
                }
            }
        }
        // Keep the complete signed mark and its white tile inside a smaller Dock canvas.
        .frame(width: placement == .dock ? size * 0.88 * 0.86 : size,
               height: placement == .dock ? size * 0.88 * 0.86 : size)
        .frame(width: placement == .dock ? size * 0.88 : size,
               height: placement == .dock ? size * 0.88 : size)
        .background {
            if placement == .dock {
                RoundedRectangle(cornerRadius: size * 0.88 * 0.22).fill(Color.white)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

import AppKit
import SwiftUI

/// Supplies the signed burgundy-and-black identity bundled with BatonUI.
public enum BatonBrand {
    /// Loads the compact logo with its light backing and I.A maker's signature.
    public static func nativeIcon() -> NSImage? {
        guard let url = Bundle.module.url(forResource: "baton-icon", withExtension: "png", subdirectory: "Brand") else { return nil }
        return NSImage(contentsOf: url)
    }
}

/// Displays the compact signed logo as quiet decoration beside explanatory copy.
public struct BrandMark: View {
    private let size: CGFloat

    /// Creates the signed logo at a size appropriate to its surrounding content.
    public init(size: CGFloat = 96) { self.size = size }

    public var body: some View {
        Group {
            if let icon = BatonBrand.nativeIcon() {
                Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

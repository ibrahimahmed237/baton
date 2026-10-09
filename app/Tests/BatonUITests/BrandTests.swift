import AppKit
import SwiftUI
import Testing
@testable import BatonUI

@Suite(.serialized)
struct BrandTests {
    @MainActor @Test
    func bundledMarkHasTransparentMarginsAndNoWhiteTile() throws {
        let image = try #require(BatonBrand.nativeIcon())
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        var solid = 0
        var white = 0
        var transparent = 0
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: 4) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: 4) {
                let color = try #require(bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB))
                if color.alphaComponent < 0.1 { transparent += 1 }
                if color.alphaComponent > 0.9 {
                    solid += 1
                    if min(color.redComponent, color.greenComponent, color.blueComponent) > 0.9 { white += 1 }
                }
            }
        }
        #expect(solid > 1000)
        #expect(transparent > solid / 2)
        #expect(white < solid / 100)
        #expect(try #require(bitmap.colorAt(x: 0, y: 0)).alphaComponent < 0.1)
    }

    @MainActor @Test
    func logoAndMenuUseDifferentDarkBacking() throws {
        let directory = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var data: [Theme: Data] = [:]
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: BrandMark(size: 92).batonTheme(theme))
            renderer.scale = 2
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            data[theme] = png
            #expect(image.size == NSSize(width: 92, height: 92))
            try png.write(to: directory.appendingPathComponent("UI6-brand-\(theme.rawValue).png"))
        }
        #expect(data[.light] != data[.graphite])
        for reduced in [false, true] {
            let renderer = ImageRenderer(content: BrandMark(size: 92, reduceTransparency: reduced).batonTheme(.graphite))
            renderer.scale = 2
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let backing = try #require(bitmap.colorAt(x: 2, y: bitmap.pixelsHigh / 2))
            #expect(reduced ? backing.alphaComponent > 0.99 : backing.alphaComponent < 0.95)
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            try png.write(to: directory.appendingPathComponent("UI6-brand-graphite-reduced-\(reduced).png"))
        }
        let opaqueMenu = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite, reduceTransparency: true))
        let translucentMenu = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite, reduceTransparency: false))
        #expect(opaqueMenu.tiffRepresentation != translucentMenu.tiffRepresentation)
        let opaqueDock = try #require(BatonBrand.applicationIcon(theme: .graphite, reduceTransparency: true))
        let translucentDock = try #require(BatonBrand.applicationIcon(theme: .graphite, reduceTransparency: false))
        #expect(opaqueDock.tiffRepresentation != translucentDock.tiffRepresentation)
        let light = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .light))
        let dark = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite))
        #expect(!light.isTemplate && !dark.isTemplate)
        #expect(light.tiffRepresentation != dark.tiffRepresentation)
    }
}

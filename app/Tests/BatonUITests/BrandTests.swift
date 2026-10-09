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
    func contentHasNoTileAndDockStaysWhiteWithoutChangingArtwork() throws {
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
            try png.write(to: directory.appendingPathComponent("UI8-brand-\(theme.rawValue).png"))
        }
        for theme in Theme.allCases {
            let content = ImageRenderer(content: BrandMark(size: 92).batonTheme(theme))
            content.scale = 2
            let image = try #require(content.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let pixels = try #require(NSBitmapImageRep(data: tiff))
            #expect(try #require(pixels.colorAt(x: 2, y: pixels.pixelsHigh / 2)).alphaComponent < 0.1)
            #expect(try #require(pixels.colorAt(x: pixels.pixelsWide / 2, y: 2)).alphaComponent < 0.1)
            let dock = try #require(BatonBrand.applicationIcon(theme: theme))
            let dockTiff = try #require(dock.tiffRepresentation)
            let dockPixels = try #require(NSBitmapImageRep(data: dockTiff))
            let border = try #require(dockPixels.colorAt(x: 12, y: dockPixels.pixelsHigh / 2)?.usingColorSpace(.deviceRGB))
            #expect(border.alphaComponent > 0.99)
            #expect(min(border.redComponent, border.greenComponent, border.blueComponent) > 0.99)
            let png = try #require(dockPixels.representation(using: .png, properties: [:]))
            try png.write(to: directory.appendingPathComponent("UI8-dock-\(theme.rawValue).png"))
        }
        let lightMark = try #require(NSBitmapImageRep(data: try requireData(data[.light])))
        let darkMark = try #require(NSBitmapImageRep(data: try requireData(data[.graphite])))
        for y in stride(from: 0, to: lightMark.pixelsHigh, by: 5) {
            for x in stride(from: 0, to: lightMark.pixelsWide, by: 5) {
                #expect(lightMark.colorAt(x: x, y: y) == darkMark.colorAt(x: x, y: y))
            }
        }
        let opaqueMenu = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite, reduceTransparency: true))
        let translucentMenu = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite, reduceTransparency: false))
        #expect(opaqueMenu.tiffRepresentation == translucentMenu.tiffRepresentation)
        let light = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .light))
        let dark = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite))
        #expect(!light.isTemplate && !dark.isTemplate)
        #expect(light.tiffRepresentation == dark.tiffRepresentation)
    }
    @MainActor @Test func dockMarkUsesMoreOfItsTileAndMenuOutlineStaysTransparentOutside() throws {
        let dock = try #require(BatonBrand.applicationIcon(theme: .light))
        let dockData = try #require(dock.tiffRepresentation)
        let pixels = try #require(NSBitmapImageRep(data: dockData))
        var left = pixels.pixelsWide; var right = 0
        for y in stride(from: 0, to: pixels.pixelsHigh, by: 2) {
            for x in stride(from: 0, to: pixels.pixelsWide, by: 2) {
                guard let color = pixels.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { continue }
                if color.alphaComponent > 0.9 && max(color.redComponent, color.greenComponent, color.blueComponent) < 0.7 {
                    left = min(left, x); right = max(right, x)
                }
            }
        }
        #expect(Double(right - left) > Double(pixels.pixelsWide) * 0.74)
        let menu = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: .graphite))
        let data = try #require(menu.tiffRepresentation)
        let tiny = try #require(NSBitmapImageRep(data: data))
        var whiteEdge = 0
        for y in 0..<tiny.pixelsHigh {
            for x in 0..<tiny.pixelsWide {
                let c = try #require(tiny.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB))
                if c.alphaComponent > 0.2 && min(c.redComponent, c.greenComponent, c.blueComponent) > 0.85 { whiteEdge += 1 }
            }
        }
        #expect(whiteEdge > 15)
        #expect(try #require(tiny.colorAt(x: 0, y: tiny.pixelsHigh / 2)).alphaComponent < 0.1)
    }
    private func requireData(_ value: Data?) throws -> Data { try #require(value) }

}

// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Baton",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "BatonKit", targets: ["BatonKit"]),
        .executable(name: "Baton", targets: ["Baton"])
    ],
    targets: [
        .target(name: "BatonKit"),
        .executableTarget(
            name: "Baton", dependencies: ["BatonKit"], path: ".",
            exclude: ["Tests", "Sources/BatonKit", "README.md"],
            sources: ["Sources/Baton"], resources: [.copy("Fixtures")]
        ),
        .testTarget(name: "BatonKitTests", dependencies: ["BatonKit"])
    ]
)

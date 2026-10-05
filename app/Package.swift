// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Baton",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "BatonKit", targets: ["BatonKit"]),
        .library(name: "BatonUI", targets: ["BatonUI"]),
        .executable(name: "Baton", targets: ["Baton"])
    ],
    targets: [
        .target(name: "BatonKit"),
        .target(name: "BatonUI", dependencies: ["BatonKit"]),
        .executableTarget(
            name: "Baton", dependencies: ["BatonKit", "BatonUI"], path: ".",
            exclude: ["Tests", "Sources/BatonKit", "Sources/BatonUI", "Snapshots", "README.md"],
            sources: ["Sources/Baton"], resources: [.copy("Fixtures")]
        ),
        .testTarget(name: "BatonKitTests", dependencies: ["BatonKit"]),
        .testTarget(name: "BatonUITests", dependencies: ["BatonUI", "BatonKit"])
    ]
)

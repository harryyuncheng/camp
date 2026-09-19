// swift-tools-version: 5.8
import PackageDescription

let package = Package(
    name: "camp",
    platforms: [.macOS(.v13), .iOS("17.0")],
    products: [
        .library(name: "LunchCore", targets: ["LunchCore"]),
        .library(name: "LunchUI", targets: ["LunchUI"]),
        .executable(name: "LunchMac", targets: ["LunchMac"])
    ],
    targets: [
        .target(name: "LunchCore"),
        .target(name: "LunchUI", dependencies: ["LunchCore"]),
        .executableTarget(name: "LunchMac", dependencies: ["LunchCore", "LunchUI"]),
        .testTarget(name: "LunchCoreTests", dependencies: ["LunchCore", "LunchUI"]),
        .testTarget(name: "LunchMacTests", dependencies: ["LunchMac", "LunchCore"])
    ]
)

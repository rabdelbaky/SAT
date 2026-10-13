// swift-tools-version:5.5
import PackageDescription

let package = Package(
    name: "swift-missing-deps",
    dependencies: [
        .package(url: "https://invalid.invalid/fixture/swift-thing.git", from: "1.0.0"),
    ],
    targets: [
        .target(name: "Calc", dependencies: [.product(name: "Thing", package: "swift-thing")]),
        .testTarget(name: "CalcTests", dependencies: ["Calc"]),
    ]
)

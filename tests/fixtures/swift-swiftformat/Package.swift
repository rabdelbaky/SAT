// swift-tools-version:5.5
import PackageDescription

let package = Package(
    name: "swift-swiftformat",
    targets: [
        .target(name: "Calc"),
        .testTarget(name: "CalcTests", dependencies: ["Calc"]),
    ]
)

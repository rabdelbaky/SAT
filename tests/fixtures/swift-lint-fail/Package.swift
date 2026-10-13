// swift-tools-version:5.5
import PackageDescription

let package = Package(
    name: "swift-lint-fail",
    targets: [
        .target(name: "Calc"),
        .testTarget(name: "CalcTests", dependencies: ["Calc"]),
    ]
)

// swift-tools-version: 6.0
// The swift_gate live fixture: one library at the macOS 14 floor, in language mode 6.
import PackageDescription

let package = Package(
  name: "Floor",
  platforms: [.macOS(.v14)],
  targets: [
    .target(name: "Floor"),
    .testTarget(name: "FloorTests", dependencies: ["Floor"]),
  ]
)

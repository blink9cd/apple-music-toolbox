// swift-tools-version: 6.0
// listensmith's Music.app adapter: a tested core, a thin live layer, and the executable.
import PackageDescription

let package = Package(
  name: "Scrobbler",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "scrobbler", targets: ["scrobbler"])],
  targets: [
    .target(name: "ScrobblerCore"),
    .target(name: "ScrobblerLive", dependencies: ["ScrobblerCore"]),
    .executableTarget(name: "scrobbler", dependencies: ["ScrobblerCore", "ScrobblerLive"]),
    // The unit tests never see the live layer: the first half of the tripwire that keeps
    // every test off the real host.
    .testTarget(name: "ScrobblerCoreTests", dependencies: ["ScrobblerCore"]),
    // The operator's live smoke test; every test in it is disabled unless SCROBBLER_LIVE=1.
    .testTarget(name: "ScrobblerLiveTests", dependencies: ["ScrobblerCore", "ScrobblerLive"]),
  ]
)

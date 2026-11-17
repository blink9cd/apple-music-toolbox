// swift-tools-version: 6.0
// Apple Music Toolbox Runner: the small signed app launchd starts in front of Python, so
// macOS charges Music.app automation to the app rather than to the interpreter. A tested
// core, a thin live layer, and the executable.
import PackageDescription

let package = Package(
  name: "Runner",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "runner", targets: ["runner"])],
  targets: [
    .target(name: "RunnerCore"),
    .target(name: "RunnerLive", dependencies: ["RunnerCore"]),
    .executableTarget(name: "runner", dependencies: ["RunnerCore", "RunnerLive"]),
    // The unit tests never see the live layer: nothing they run can spawn a process.
    .testTarget(name: "RunnerCoreTests", dependencies: ["RunnerCore"]),
    // Spawns /usr/bin/true and /bin/sh only, and only with RUNNER_LIVE=1.
    .testTarget(name: "RunnerLiveTests", dependencies: ["RunnerCore", "RunnerLive"]),
  ]
)

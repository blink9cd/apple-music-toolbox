import Testing

@testable import ScrobblerCore

/// The tripwire's answers: a test runner is refused unless the live switch is on, and
/// anything else is allowed.
@Suite struct LiveGuardTests {
  static let app = "/Applications/listensmith scrobbler.app/Contents/MacOS/scrobbler"
  static let helper = "/usr/bin/swiftpm-testing-helper"
  static let live = ["SCROBBLER_LIVE": "1"]

  @Test func aTestRunnerWithoutTheSwitchIsRefused() {
    #expect(!LiveGuard.liveBridgeAllowed(environment: [:], processPath: Self.helper))
  }

  @Test func aTestRunnerWithTheSwitchIsAllowed() {
    #expect(LiveGuard.liveBridgeAllowed(environment: Self.live, processPath: Self.helper))
  }

  @Test func theAppWithoutTheSwitchIsAllowed() {
    #expect(LiveGuard.liveBridgeAllowed(environment: [:], processPath: Self.app))
  }

  @Test func theAppWithTheSwitchIsAllowed() {
    #expect(LiveGuard.liveBridgeAllowed(environment: Self.live, processPath: Self.app))
  }

  @Test(arguments: [
    "/usr/bin/xctest",
    "/tmp/build/ScrobblerPackageTests.xctest/Contents/MacOS/ScrobblerPackageTests",
    "swiftpm-testing-helper",
  ])
  func everyRunnerShapeIsRefused(path: String) {
    #expect(!LiveGuard.liveBridgeAllowed(environment: [:], processPath: path))
  }

  @Test(arguments: ["0", "true", "", " 1"])
  func onlyTheExactSwitchValueAllows(value: String) {
    let environment = ["SCROBBLER_LIVE": value]
    #expect(!LiveGuard.liveBridgeAllowed(environment: environment, processPath: Self.helper))
  }

  @Test func aNameThatOnlyContainsARunnersNameIsNotOne() {
    let path = "/opt/tools/xctest-notes/my-xctest"
    #expect(LiveGuard.liveBridgeAllowed(environment: [:], processPath: path))
  }
}

/// The tripwire: whether the live Music bridge may exist in this process.
///
/// The unit tests never link the live layer, which is the first half. This is the second:
/// should a test runner ever create the live bridge anyway, the bridge stops the process
/// before it can reach Music, unless the live smoke test was asked for by name.
public enum LiveGuard {
  /// The one value of SCROBBLER_LIVE that turns the live smoke test on.
  static let switchOn = "1"
  /// The names a test runner's process goes by.
  static let runnerNames: Set<String> = ["xctest", "swiftpm-testing-helper"]
  /// The suffix of a test bundle, which a runner's process may run from inside.
  static let bundleSuffix = ".xctest"

  /// False inside a test runner (an `.xctest` bundle path, or a process named `xctest` or
  /// `swiftpm-testing-helper`) unless SCROBBLER_LIVE is "1". The live bridge stops the
  /// process when this is false: the tripwire.
  public static func liveBridgeAllowed(environment: [String: String], processPath: String)
    -> Bool
  {
    // The name is spelled out, so the project's scan of environment reads can check it is
    // declared to the gate cache.
    environment["SCROBBLER_LIVE"] == switchOn || !isTestRunner(processPath)
  }

  /// Whether `processPath` is a test runner's: named as one, or inside a test bundle.
  static func isTestRunner(_ processPath: String) -> Bool {
    let components = processPath.split(separator: "/")
    if let name = components.last, runnerNames.contains(String(name)) { return true }
    return components.contains { $0.hasSuffix(bundleSuffix) }
  }
}

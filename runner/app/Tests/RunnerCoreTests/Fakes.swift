@testable import RunnerCore

/// A spawner that records each argv it is asked to start and answers from set values. It
/// starts nothing: the unit tests never reach a real process.
final class FakeSpawner: Spawner {
  /// The pid every successful spawn answers with.
  static let pid: Int32 = 4242

  /// The wait status `wait` returns.
  let waitStatus: Int32
  /// The error `spawn` throws instead of starting, when set.
  let failure: RunnerError?
  /// Each argv `spawn` was given, in order.
  private(set) var spawned: [[String]] = []
  /// Each pid `wait` was given, in order.
  private(set) var waited: [Int32] = []

  init(waitStatus: Int32, failure: RunnerError? = nil) {
    self.waitStatus = waitStatus
    self.failure = failure
  }

  func spawn(_ argv: [String]) throws(RunnerError) -> Int32 {
    spawned.append(argv)
    if let failure { throw failure }
    return Self.pid
  }

  func wait(_ pid: Int32) -> Int32 {
    waited.append(pid)
    return waitStatus
  }
}

/// Collects each line `Supervisor.run` reports.
final class ReportLog {
  /// The lines, in order.
  private(set) var lines: [String] = []

  /// Record one line.
  func add(_ line: String) {
    lines.append(line)
  }
}

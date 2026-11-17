// The runner's whole decision, with each real-host step injected, so the executable is a
// thin wiring of live pieces into this one tested function.

/// Starts and waits on one child process. The live implementation uses `posix_spawn`,
/// never `exec`: the runner must stay the process macOS holds responsible.
public protocol Spawner {
  /// Start `argv` (its first element is the program's path); returns the child's pid.
  func spawn(_ argv: [String]) throws(RunnerError) -> Int32
  /// Wait for `pid` to end; returns its wait status.
  func wait(_ pid: Int32) -> Int32
}

/// Runs one allowlisted script under its interpreter and returns the runner's exit code.
public enum Supervisor {
  /// Parse `arguments`, verify the bundle, load and check the allowlist, spawn
  /// `[python, script] + rest`, wait, and map the child's status. The self-check runs
  /// before the allowlist is read, because only a verified bundle's Info.plist is trusted.
  /// Each refusal or failure is one `report("ERROR: ...")` line and its exit code.
  public static func run(
    arguments: [String], allowlist: () -> Allowlist?, selfCheck: () -> Bool,
    spawner: any Spawner, report: (String) -> Void
  ) -> Int32 {
    do throws(RunnerError) {
      let call = try Arguments.parse(arguments)
      guard selfCheck() else { throw .selfCheckFailed }
      guard let list = allowlist() else { throw .allowlistUnreadable }
      try list.check(python: call.python, script: call.script)
      let pid = try spawner.spawn([call.python, call.script] + call.rest)
      return ExitStatus.code(waitStatus: spawner.wait(pid))
    } catch {
      report("ERROR: \(error.message)")
      return error.exitCode
    }
  }
}

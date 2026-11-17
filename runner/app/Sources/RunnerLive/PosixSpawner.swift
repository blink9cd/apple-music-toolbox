// The real-host spawner. Excluded from region coverage as a live seam and proven by the
// RUNNER_LIVE suite instead, so it holds no decision a unit test would need to reach.
import Darwin
import RunnerCore

/// Starts the child with `posix_spawn`, forwards the ending signals to it, and waits on it.
public struct PosixSpawner: Spawner {
  /// The signals launchd and a terminal send to end a job, forwarded to the child.
  static let forwarded: [Int32] = [SIGTERM, SIGINT, SIGHUP]
  /// Signals the child starts with at their default action whatever the runner's are: the
  /// forwarded ones, which the runner ignores, and SIGCHLD, which a parent may have ignored.
  static let resetInChild: [Int32] = forwarded + [SIGCHLD]
  /// The wait status returned when `waitpid` fails: it maps to exit 1, never to success.
  static let waitFailedStatus: Int32 = 1 << 8

  /// The forwarder this spawner arms; public so a live test can disarm it afterward.
  public let forwarder = SignalForwarder()

  public init() {}

  public func spawn(_ argv: [String]) throws(RunnerError) -> Int32 {
    // An ignored SIGCHLD makes the kernel reap the child itself, and waitpid then fails.
    signal(SIGCHLD, SIG_DFL)
    // Armed before the spawn, so a SIGTERM from here on is forwarded rather than ending
    // the runner with the child still running.
    guard forwarder.arm(Self.forwarded) else { throw .spawnFailed(ETIMEDOUT) }
    var attributes = try Self.childSignalAttributes()
    defer { posix_spawnattr_destroy(&attributes) }
    var pid: pid_t = 0
    let cargs: [UnsafeMutablePointer<CChar>?] = argv.map { strdup($0) } + [nil]
    defer { for arg in cargs { free(arg) } }
    // posix_spawn, never exec: an exec keeps the pid and hands responsibility for the
    // automation back to the interpreter, so the runner must stay alive as the parent.
    // The child inherits this process's environment.
    let result = posix_spawn(&pid, argv[0], nil, &attributes, cargs, environ)
    // On failure the sources stay armed: the runner exits 1 at once.
    if result != 0 { throw .spawnFailed(result) }
    forwarder.target(pid)
    return pid
  }

  public func wait(_ pid: Int32) -> Int32 {
    var status: Int32 = 0
    while true {
      if waitpid(pid, &status, 0) != -1 { return status }
      // A forwarded signal interrupts the wait; retry. Any other failure (ECHILD) means the
      // child's status is lost, which must not read as success.
      if errno != EINTR { return Self.waitFailedStatus }
    }
  }

  /// Spawn attributes giving the child the default action for each of `resetInChild` and
  /// an empty signal mask. A spawned child inherits ignored signals, and the forwarder
  /// ignores the forwarded ones here, so without this the child would ignore a SIGTERM.
  static func childSignalAttributes() throws(RunnerError) -> posix_spawnattr_t? {
    var attributes: posix_spawnattr_t?
    try check(posix_spawnattr_init(&attributes))
    do throws(RunnerError) {
      var defaults = sigset_t()
      var mask = sigset_t()
      try checkSet(sigemptyset(&defaults))
      try checkSet(sigemptyset(&mask))
      for number in resetInChild { try checkSet(sigaddset(&defaults, number)) }
      try check(posix_spawnattr_setsigdefault(&attributes, &defaults))
      try check(posix_spawnattr_setsigmask(&attributes, &mask))
      let flags = Int16(POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK)
      try check(posix_spawnattr_setflags(&attributes, flags))
    } catch {
      posix_spawnattr_destroy(&attributes)
      throw error
    }
    return attributes
  }

  /// Throw `.spawnFailed` for a nonzero posix_spawnattr result, which is the error number.
  static func check(_ result: Int32) throws(RunnerError) {
    if result != 0 { throw .spawnFailed(result) }
  }

  /// Throw `.spawnFailed` with errno when a sigset call returns -1.
  static func checkSet(_ result: Int32) throws(RunnerError) {
    if result != 0 { throw .spawnFailed(errno) }
  }
}

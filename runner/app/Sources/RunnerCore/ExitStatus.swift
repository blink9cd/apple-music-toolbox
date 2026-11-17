// The runner exits with its child's status, so launchd and the caller see the job's own
// result. The macros that decode a wait status do not import into Swift, so this restates
// their arithmetic.

/// Maps a `waitpid` status to the runner's exit code.
public enum ExitStatus {
  /// The low seven bits: 0 for a normal exit, the signal number for a signal death.
  static let signalMask: Int32 = 0x7f
  /// The low bits a stopped child reports.
  static let stopped: Int32 = 0x7f
  /// A normal exit's code sits in the byte above the low seven bits and the core flag.
  static let exitShift: Int32 = 8
  static let exitMask: Int32 = 0xff
  /// The shell's convention for a signal death: 128 plus the signal number.
  static let signalBase: Int32 = 128
  /// A stopped child is not a result; `waitpid` reports one only when asked to.
  static let stoppedCode: Int32 = 1

  /// The exit code for `waitStatus`: the child's own code, or 128 plus the signal.
  public static func code(waitStatus: Int32) -> Int32 {
    let low = waitStatus & signalMask
    if low == 0 { return (waitStatus >> exitShift) & exitMask }  // exited
    if low != stopped { return signalBase + low }  // killed by a signal
    return stoppedCode  // stopped: not expected
  }
}

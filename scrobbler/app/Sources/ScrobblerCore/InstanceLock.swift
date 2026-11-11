import Foundation

/// The single-instance lock: while one is held, a second copy of the app started by hand
/// cannot take it, so two copies never count the same play.
///
/// An exclusive `flock` on the lock file. The kernel drops it when the descriptor closes,
/// which happens when the lock is released or the process ends, however it ends.
public final class InstanceLock: Sendable {
  /// The open lock file holding the lock.
  private let descriptor: Int32

  private init(descriptor: Int32) {
    self.descriptor = descriptor
  }

  /// Take the lock at `url`, making its folder if needed. Never waits: a lock another
  /// process has taken is `.held`, and a lock file that cannot be opened, a symlink where
  /// it belongs included, is `.unopenable`.
  public static func acquire(at url: URL) -> LockAttempt {
    // A folder that cannot be made fails the open just below, which is the one answer.
    try? FileIO.makeFolder(url.deletingLastPathComponent())
    let flags = O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC
    let descriptor = open(url.path, flags, FileIO.privateFileMode)
    guard descriptor >= 0 else { return .unopenable }
    guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
      close(descriptor)
      return .held
    }
    return .acquired(InstanceLock(descriptor: descriptor))
  }

  /// Releasing the last reference closes the file, which releases the lock.
  deinit {
    close(descriptor)
  }
}

/// What one attempt at the instance lock came to.
public enum LockAttempt: Sendable {
  /// The lock is this process's for as long as the value lives.
  case acquired(InstanceLock)
  /// Another process holds it: a copy of the app is already running.
  case held
  /// The lock file could not be opened, so whether another copy runs is unknown.
  case unopenable

  /// Whether another process holds the lock.
  public var isHeld: Bool {
    if case .held = self { return true }
    return false
  }

  /// Whether the lock file could not be opened.
  public var isUnopenable: Bool {
    if case .unopenable = self { return true }
    return false
  }
}

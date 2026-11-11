import Foundation

/// Collapses a burst of playerInfo notices into the newest one.
///
/// Music posts duplicate notices, and a scrub as a paused notice and a playing notice about
/// 25 ms apart. Each notice restarts the window, and only the newest notice of a window that
/// passed quietly is handed on, so a scrub's pair arrives as the one `playing` notice and the
/// position read finds the jump.
public struct Debouncer: Sendable {
  /// The quiet time, in seconds, a notice must outlast before it is handed on.
  public static let window: Double = 0.25

  /// The newest notice offered and not yet fired.
  private var pending: PlayerNotice?
  /// When `pending` may fire.
  private var deadline: Double = 0

  /// A debouncer holding nothing.
  public init() {}

  /// Hold `notice` as the newest, and return the time at which to call `fire`.
  public mutating func offer(_ notice: PlayerNotice, at time: Double) -> Double {
    pending = notice
    deadline = time + Self.window
    return deadline
  }

  /// The newest notice once its window has passed, or nil: nothing is held, or a newer
  /// notice moved the deadline past `time`, and its own deadline's call will fire it.
  public mutating func fire(at time: Double) -> PlayerNotice? {
    guard let notice = pending, time >= deadline else { return nil }
    pending = nil
    return notice
  }
}

// The coordinator's timers over the main run loop.
//
// Excluded from coverage as a real-host seam: it only hands work to `Timer`. The Scheduler
// contract holds because the run loop retains a scheduled timer until it is invalidated,
// so a task runs whether or not its handle is kept.
import Foundation
import ScrobblerCore

/// `Scheduler` over `Timer`s on the main run loop, each with a tolerance of a tenth of its
/// interval, so the system can coalesce wakeups.
@MainActor public final class RunLoopScheduler: Scheduler {
  /// The share of an interval a timer may fire late by.
  static let toleranceShare = 0.1

  /// A scheduler on the main run loop.
  public init() {}

  /// Run `body` every `every` seconds until canceled.
  public func repeating(every: Double, _ body: @escaping @MainActor () -> Void)
    -> any Cancellable
  {
    schedule(after: every, repeats: true, body)
  }

  /// Run `body` once, `after` seconds from now. The run loop invalidates a one-shot timer
  /// once it fires, so nothing can fire it again.
  public func once(after: Double, _ body: @escaping @MainActor () -> Void) -> any Cancellable {
    schedule(after: after, repeats: false, body)
  }

  /// A timer on the current run loop, the main one, since this scheduler is main-actor.
  private func schedule(
    after interval: Double, repeats: Bool, _ body: @escaping @MainActor () -> Void
  ) -> any Cancellable {
    let timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: repeats) { _ in
      MainActor.assumeIsolated { body() }
    }
    timer.tolerance = interval * Self.toleranceShare
    return TimerTask(timer: timer)
  }
}

/// A scheduled timer's handle: canceling it invalidates the timer, which then never fires.
@MainActor final class TimerTask: Cancellable {
  private let timer: Timer

  init(timer: Timer) {
    self.timer = timer
  }

  /// Stop the timer; invalidating one already fired or invalidated does nothing.
  func cancel() {
    timer.invalidate()
  }
}

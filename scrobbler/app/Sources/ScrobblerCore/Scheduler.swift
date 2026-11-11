/// A task a `Scheduler` started, which can be stopped.
public protocol Cancellable: AnyObject {
  /// Stop the task; a stopped task never runs again.
  @MainActor func cancel()
}

/// The coordinator's timers, on the main actor.
///
/// The live layer implements it over the main run loop; tests implement it over a manual
/// clock, so a whole scenario runs in no time and in a fixed order.
///
/// Every implementation keeps one contract: a task runs until it is canceled or, for a
/// one-shot task, until it has fired, whether or not the caller keeps its handle. Dropping
/// a handle never stops a task; only `cancel` does.
public protocol Scheduler: AnyObject {
  /// Run `body` every `every` seconds, the first time `every` seconds from now.
  @MainActor func repeating(every: Double, _ body: @escaping @MainActor () -> Void)
    -> any Cancellable
  /// Run `body` once, `after` seconds from now.
  @MainActor func once(after: Double, _ body: @escaping @MainActor () -> Void) -> any Cancellable
}

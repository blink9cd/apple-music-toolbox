// Relays the signals that end a job to the child, so launchd's SIGTERM reaches the Python
// process doing the work rather than only the runner in front of it.
import Darwin
import Dispatch
import Foundation

/// Forwards signals from the runner to its child. Armed before the spawn and pointed at
/// the child after it, so no signal can arrive while the runner would still die of it and
/// leave the child orphaned.
public final class SignalForwarder: @unchecked Sendable {
  // @unchecked: every mutable field below is read and written only under `lock`.

  /// How long `arm` waits for the kernel to register each dispatch source.
  static let registrationTimeout: DispatchTimeInterval = .seconds(5)

  private let lock = NSLock()
  /// The child's pid once `target` has run; 0 until then.
  private var child: pid_t = 0
  /// Signals that arrived before the child existed, delivered by `target`.
  private var pending: [Int32] = []
  /// The live sources; each lives only while referenced.
  private var sources: [DispatchSourceSignal] = []
  /// Each armed signal's disposition before `arm`, restored by `disarm`.
  private var previous: [(Int32, sig_t?)] = []

  public init() {}

  /// Start catching `signals`. Each dispatch source is registered with the kernel before its
  /// signal is set to ignored: until then the signal keeps its default action, which kills
  /// only the runner, before any child exists. After it, the source sees the signal (a
  /// dispatch signal source fires for an ignored signal) and `deliver` relays it.
  /// Returns false when a source did not register in time, or a signal could not be set
  /// to ignored.
  public func arm(_ signals: [Int32]) -> Bool {
    let queue = DispatchQueue.global(qos: .utility)
    for number in signals {
      let registered = DispatchSemaphore(value: 0)
      let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
      source.setRegistrationHandler { registered.signal() }
      source.setEventHandler { [self] in deliver(number) }
      source.resume()
      lock.withLock { sources.append(source) }
      guard registered.wait(timeout: .now() + Self.registrationTimeout) == .success else {
        return false
      }
      let old = signal(number, SIG_IGN)
      // SIG_ERR: the kernel refused the change (a signal that cannot be ignored), so the
      // signal keeps its default action and would end the runner over a live child.
      guard !Self.isError(old) else { return false }
      lock.withLock { previous.append((number, old)) }
    }
    return true
  }

  /// Whether `disposition` is `SIG_ERR`, what `signal` returns when it fails. A C function
  /// pointer has no `==`, so the two are compared as the addresses they are.
  static func isError(_ disposition: sig_t?) -> Bool {
    unsafeBitCast(disposition, to: Int.self) == unsafeBitCast(SIG_ERR, to: Int.self)
  }

  /// Point the forwarder at `pid`, and deliver any signal that arrived before it existed.
  public func target(_ pid: pid_t) {
    let early = lock.withLock {
      child = pid
      defer { pending = [] }
      return pending
    }
    for number in early { kill(pid, number) }
  }

  /// Stop forwarding and restore each signal's earlier disposition. The runner never calls
  /// this (it forwards until it exits); the live tests do, so the test process is left as
  /// it was found.
  public func disarm() {
    let (armed, old) = lock.withLock {
      defer {
        sources = []
        previous = []
        child = 0
      }
      return (sources, previous)
    }
    for (number, disposition) in old.reversed() { signal(number, disposition) }
    for source in armed { source.cancel() }
  }

  /// The signals held for a child not yet targeted; read by the live tests.
  var pendingSignals: [Int32] {
    lock.withLock { pending }
  }

  /// Relay `number` to the child, or hold it until there is one.
  private func deliver(_ number: Int32) {
    let pid: pid_t? = lock.withLock {
      if child == 0 {
        pending.append(number)
        return nil
      }
      return child
    }
    if let pid { kill(pid, number) }
  }
}

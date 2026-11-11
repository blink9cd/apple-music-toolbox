import Foundation

/// What one drain came to.
public enum DrainOutcome: Sendable, Equatable {
  /// Every queued file was sent or refused.
  case drained
  /// The drain stopped at a file kept for later, before sending anything, or after
  /// sending the rest past a file it could not read; `error` is the drainer's fixed
  /// wording.
  case stopped(error: String)
  /// Nothing was sent: the queue is empty, the drainer is backing off, or another drain
  /// is still in progress.
  case idle
}

/// Posts queued listens to the store, one record per request, in name order.
///
/// The store's answer decides each file: 200 (accepted, or a repeat) deletes it; 400 and
/// 413 move it to the refused folder with the store's findings; any other answer, or none,
/// keeps it, stops the drain and backs off 5, 15, 60, then 300 s, until a handled answer
/// resets the wait. The token is read afresh on each drain that has something to send and
/// is held only for that drain: never cached, logged or written.
///
/// `lastError` uses one fixed wording, which the Python status reads: `store unreachable`,
/// `store unavailable` (503), `token refused` (401), `store answered <code>`,
/// `token unreadable: <TokenError case>`, `config refused: <key>`, and `queue unreadable`
/// or `queue unwritable` for the queue folder itself.
@MainActor public final class QueueDrainer {
  /// The waits after one, two, three, and four or more failures in a row, in seconds.
  static let backoffSeconds: [Double] = [5, 15, 60, 300]
  /// The answer that accepts a record.
  static let accepted = 200
  /// The answers that refuse a record for good: bad content and too large.
  static let refusals: Set<Int> = [400, 413]
  static let tokenRefused = 401
  static let unavailable = 503
  /// The sidecar written when the store's refusal is not a JSON object.
  static let unreadableFindings = Data(#"{"findings":["store answer unreadable"]}"#.utf8)

  private let queue: QueueStore
  private let transport: any HTTPTransport
  private let config: () throws -> ScrobblerConfig
  private let token: () throws(TokenError) -> String
  private let clock: () -> Double
  /// Failures in a row since the last handled answer.
  private var failures = 0
  /// Whether a drain is in progress, awaiting an answer.
  private var isDraining = false

  /// When the next drain may send, while backing off; nil otherwise.
  public private(set) var nextAttemptAt: Double?
  /// The last failure, in the fixed wording above; nil after a handled answer.
  public private(set) var lastError: String?
  /// When the store last accepted a record.
  public private(set) var lastSentAt: Double?

  /// A drainer of `queue` through `transport`, reading `config` and `token` afresh on each
  /// drain, with `clock` giving Unix seconds.
  public init(
    queue: QueueStore, transport: any HTTPTransport,
    config: @escaping () throws -> ScrobblerConfig,
    token: @escaping () throws(TokenError) -> String, clock: @escaping () -> Double
  ) {
    self.queue = queue
    self.transport = transport
    self.config = config
    self.token = token
    self.clock = clock
  }

  /// Send the queue in name order until it is empty or an answer says to keep and wait.
  public func drain() async -> DrainOutcome {
    // One drain at a time: a second one entering while the first awaits an answer would
    // list the same files and send them again.
    guard !isDraining else { return .idle }
    isDraining = true
    defer { isDraining = false }
    if let next = nextAttemptAt, clock() < next { return .idle }
    // Any wait has passed; a stop below that does not back off must not leave it set.
    nextAttemptAt = nil
    let files: [URL]
    do { files = try queue.pending() } catch { return stop("queue unreadable", backOff: false) }
    guard !files.isEmpty else { return .idle }
    let destination: Destination
    do { destination = try prepare() } catch { return stop(error.message, backOff: false) }
    return await send(files, to: destination)
  }

  /// Post each of `files` in turn, stopping at the first answer that keeps one.
  private func send(_ files: [URL], to destination: Destination) async -> DrainOutcome {
    var skipped = false
    for file in files {
      let body: Data
      do {
        body = try queue.read(file)
      } catch {
        // A file removed since the listing is simply gone. Any other that cannot be read
        // (a symlink, a FIFO, an oversize or unreadable file) stays, and once the rest are
        // sent the drain reports it rather than calling the queue drained.
        if error.code != ENOENT { skipped = true }
        continue
      }
      let result = await transport.post(destination.url, headers: destination.headers, body: body)
      if let message = settle(file, with: result) { return stop(message, backOff: true) }
    }
    return skipped ? stop("queue unreadable", backOff: false) : .drained
  }

  /// Where this drain posts, and its headers: the config and the token, read now.
  private func prepare() throws(DrainStop) -> Destination {
    let settings: ScrobblerConfig
    do {
      settings = try config()
    } catch let error as ConfigError {
      throw DrainStop(message: "config refused: \(error.key)")
    } catch {
      throw DrainStop(message: "config refused: \(ConfigError.wholeFile)")
    }
    let secret: String
    do { secret = try token() } catch { throw DrainStop(message: "token unreadable: \(error)") }
    return Destination(
      url: settings.submitURL,
      headers: ["Authorization": "Token \(secret)", "Content-Type": "application/json"])
  }

  /// Act on the answer for `file`; the failure to stop with, or nil to go on.
  private func settle(_ file: URL, with result: TransportResult) -> String? {
    guard case .response(let status, let body) = result else { return "store unreachable" }
    do {
      switch status {
      case Self.accepted:
        try queue.remove(file)
        lastSentAt = clock()
      case _ where Self.refusals.contains(status):
        try queue.refuse(file, findings: Self.findings(from: body))
      case Self.tokenRefused: return "token refused"
      case Self.unavailable: return "store unavailable"
      default: return "store answered \(status)"
      }
    } catch {
      return "queue unwritable"
    }
    // The store handled the record, so it is up and the wait starts over.
    failures = 0
    nextAttemptAt = nil
    lastError = nil
    return nil
  }

  /// What a refusal's sidecar holds: the store's answer when it is a JSON object, and a
  /// fixed finding otherwise, so no control bytes or arbitrary text from an answer land
  /// in a file a person may later print.
  static func findings(from body: Data) -> Data {
    (try? JSONSerialization.jsonObject(with: body)) is [String: Any] ? body : unreadableFindings
  }

  /// Record `message` as the last error, back off when `backOff`, and stop the drain.
  private func stop(_ message: String, backOff: Bool) -> DrainOutcome {
    lastError = message
    if backOff {
      failures += 1
      let wait = Self.backoffSeconds[min(failures, Self.backoffSeconds.count) - 1]
      nextAttemptAt = clock() + wait
    }
    return .stopped(error: message)
  }
}

/// Where one drain posts.
private struct Destination {
  let url: URL
  let headers: [String: String]
}

/// A drain that stops before sending anything, with its fixed wording.
private struct DrainStop: Error {
  let message: String
}

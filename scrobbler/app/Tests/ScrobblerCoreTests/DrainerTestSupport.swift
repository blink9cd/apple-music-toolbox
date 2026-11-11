import Foundation
import Testing

@testable import ScrobblerCore

/// A transport that records each call and answers from a script, then with 200.
///
/// It can hold one call until the test releases it, to drive a second drain while the
/// first is suspended, and run a hook before answering, to change the queue mid-drain.
actor FakeTransport: HTTPTransport {
  /// One recorded request.
  struct Call: Sendable {
    let url: URL
    let headers: [String: String]
    let body: Data
  }

  private var answers: [TransportResult]
  private(set) var calls: [Call] = []
  private var holdNext = false
  private var held: CheckedContinuation<Void, Never>?
  private var arrival: CheckedContinuation<Void, Never>?
  private var beforeAnswer: (@Sendable (Int) -> Void)?

  init(_ answers: [TransportResult] = []) {
    self.answers = answers
  }

  /// Make the next call wait until `release`.
  func holdNextCall() {
    holdNext = true
  }

  /// Run `action` with each call's index before it is answered.
  func setBeforeAnswer(_ action: @escaping @Sendable (Int) -> Void) {
    beforeAnswer = action
  }

  /// Return once a call has arrived.
  func waitForCall() async {
    if !calls.isEmpty { return }
    await withCheckedContinuation { arrival = $0 }
  }

  /// Let the held call answer.
  func release() {
    held?.resume()
    held = nil
  }

  func post(_ url: URL, headers: [String: String], body: Data) async -> TransportResult {
    calls.append(Call(url: url, headers: headers, body: body))
    beforeAnswer?(calls.count - 1)
    arrival?.resume()
    arrival = nil
    if holdNext {
      holdNext = false
      await withCheckedContinuation { held = $0 }
    }
    return answers.isEmpty ? .response(status: 200, body: Data()) : answers.removeFirst()
  }
}

/// A drainer over a temp queue, with a settable clock and a counted token read.
@MainActor
final class Rig {
  let temp: TempFolder
  let queue: QueueStore
  let transport: FakeTransport
  var now = 1000.0
  var tokenReads = 0
  var tokenResult: Result<String, TokenError> = .success(testToken)
  var configResult: () throws -> ScrobblerConfig = { ScrobblerConfig() }
  private(set) var drainer: QueueDrainer!

  init(_ answers: [TransportResult] = []) throws {
    temp = try TempFolder()
    queue = QueueStore(queueDir: temp.child("queue"), refusedDir: temp.child("refused"))
    transport = FakeTransport(answers)
    drainer = QueueDrainer(
      queue: queue, transport: transport,
      config: { [unowned self] in try configResult() },
      token: { [unowned self] () throws(TokenError) -> String in
        tokenReads += 1
        return try tokenResult.get()
      },
      clock: { [unowned self] in now })
  }

  /// Queue `count` listens a second apart, returning their files in name order.
  @discardableResult
  func enqueue(_ count: Int) throws -> [URL] {
    try (0..<count).map { try queue.enqueue(try queuedListen(listenedAt: 1_795_000_000 + $0)).file }
  }

  /// The names still queued.
  func pendingNames() throws -> [String] {
    try queue.pending().map(\.lastPathComponent)
  }

  /// A queue file name sorting before every listen `enqueue` writes.
  func earlyName(_ piece: Int) -> URL {
    queue.queueDir.appendingPathComponent(
      "1700000000-\(testPlayID)-\(QueueStore.zeroPadded(piece, to: 3)).json")
  }
}

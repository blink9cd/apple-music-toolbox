import Foundation

/// Sends what is playing now to the relay on the loopback address, as ListenBrainz's
/// `playing_now` submit, with the same token the drainer sends to the store.
///
/// What is playing now is only worth its newest word, so nothing is ever queued: one
/// request is in flight at a time, a record published meanwhile replaces the one waiting
/// behind it, and a send that fails, is answered with anything but 200, or cannot
/// start because the config or the token cannot be read drops its record. The next
/// heartbeat or change sends a fresh one. The config and the token are read afresh for
/// each send and the token is held only for that send: never cached, logged or written.
@MainActor public final class NetworkNowPlayingSink: NowPlayingSink {
  /// The per-request timeout, in seconds: short, since a record a heartbeat replaces is
  /// not worth waiting for.
  public static let timeout: TimeInterval = 2

  private let transport: any HTTPTransport
  private let config: () throws -> ScrobblerConfig
  private let token: () throws(TokenError) -> String
  /// The newest record not yet sent; at most one waits.
  private var waiting: NowPlayingRecord?
  /// The task sending records while one is in flight, so a test can wait for it; nil when
  /// nothing is being sent.
  private(set) var sending: Task<Void, Never>?

  /// A sink posting through `transport`, reading `config` and `token` afresh on each send.
  public init(
    transport: any HTTPTransport, config: @escaping () throws -> ScrobblerConfig,
    token: @escaping () throws(TokenError) -> String
  ) {
    self.transport = transport
    self.config = config
    self.token = token
  }

  /// Send `record`, now when nothing is in flight, else once the request in flight ends,
  /// in place of any record already waiting.
  public func publish(_ record: NowPlayingRecord) {
    waiting = record
    guard sending == nil else { return }
    sending = Task { await sendWaiting() }
  }

  /// Send the waiting record, and then each that arrives while it is in flight, until
  /// none waits.
  private func sendWaiting() async {
    while let record = waiting {
      waiting = nil
      await send(record)
    }
    sending = nil
  }

  /// Post `record` once. Whatever the answer, the record is done with: it is never
  /// resent, so the result is not kept.
  private func send(_ record: NowPlayingRecord) async {
    guard let request = try? prepare(record) else { return }
    _ = await transport.post(request.url, headers: request.headers, body: request.body)
  }

  /// The relay's URL, the headers with the token read now, and `record` encoded.
  private func prepare(_ record: NowPlayingRecord) throws -> RelayRequest {
    let settings = try config()
    let secret = try token()
    return RelayRequest(
      url: settings.relayURL,
      headers: ["Authorization": "Token \(secret)", "Content-Type": "application/json"],
      body: try RecordCoding.encode(record))
  }
}

/// One post to the relay.
private struct RelayRequest {
  let url: URL
  let headers: [String: String]
  let body: Data
}

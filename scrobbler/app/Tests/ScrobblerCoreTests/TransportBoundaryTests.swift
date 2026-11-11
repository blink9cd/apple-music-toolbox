import Foundation
import Testing

@testable import ScrobblerCore

/// The real transport, driven against a listener the test binds on 127.0.0.1 at a
/// kernel-picked port. No other address is ever contacted.
@Suite(.serialized) struct TransportBoundaryTests {
  /// The headers the drainer sends.
  private let headers = ["Authorization": "Token \(testToken)", "Content-Type": "application/json"]

  /// The submit URL at `server`'s port.
  private func url(of server: LoopbackServer) -> URL {
    ScrobblerConfig(storePort: server.port).submitURL
  }

  @Test func aPostArrivesWithItsRequestLineTokenAndBody() async throws {
    let answer = Data(#"{"status":"ok"}"#.utf8)
    let server = try LoopbackServer(reply: .bytes(httpAnswer(status: 200, body: answer)))
    defer { server.stop() }
    let body = Data(#"{"listen_type":"single"}"#.utf8)
    let result = await LoopbackTransport().post(url(of: server), headers: headers, body: body)
    #expect(result == .response(status: 200, body: answer))
    let request = try #require(String(bytes: server.request, encoding: .utf8))
    #expect(request.hasPrefix("POST /1/submit-listens HTTP/1.1\r\n"))
    #expect(request.lowercased().contains("\r\nauthorization: token \(testToken)\r\n"))
    #expect(request.hasSuffix("\r\n\r\n" + #"{"listen_type":"single"}"#))
  }

  @Test func aRedirectComesBackAsItselfAndIsNeverFollowed() async throws {
    let target = try LoopbackServer(reply: nil)
    defer { target.stop() }
    let location = "Location: http://127.0.0.1:\(target.port)/"
    let server = try LoopbackServer(reply: .bytes(httpAnswer(status: 302, headers: [location])))
    defer { server.stop() }
    let result = await LoopbackTransport().post(url(of: server), headers: headers, body: Data())
    #expect(result == .response(status: 302, body: Data()))
    #expect(!target.hasPendingConnection())
  }

  @Test func aLargeAnswerIsReadOnlyToTheCap() async throws {
    let large = Data(repeating: UInt8(ascii: "a"), count: 200 * 1024)
    let server = try LoopbackServer(reply: .bytes(httpAnswer(status: 400, body: large)))
    defer { server.stop() }
    let result = await LoopbackTransport().post(url(of: server), headers: headers, body: Data())
    #expect(result == .response(status: 400, body: large.prefix(LoopbackTransport.maxBodyBytes)))
  }

  @Test func aListenerThatNeverAnswersTimesOut() async throws {
    let server = try LoopbackServer(reply: .silent)
    defer { server.stop() }
    let started = Date()
    let result = await LoopbackTransport(timeout: 0.5).post(
      url(of: server), headers: headers, body: Data())
    guard case .failed(let reason) = result else {
      Issue.record("expected a failure, got \(result)")
      return
    }
    #expect(reason.hasPrefix("URL error"))
    #expect(!reason.contains(testToken))
    #expect(Date().timeIntervalSince(started) < 5)
  }

  @Test func theDefaultTimeoutIsTenSeconds() {
    #expect(LoopbackTransport().timeout == 10)
    #expect(LoopbackTransport.defaultTimeout == 10)
    #expect(LoopbackTransport(timeout: 0.5).session.configuration.timeoutIntervalForRequest == 0.5)
  }
}

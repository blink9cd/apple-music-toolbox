import Foundation
import Testing

@testable import ScrobblerCore

// The relay sink and the fan-out. The real transport is driven against a listener the test
// binds on 127.0.0.1 at a kernel-picked port; the in-flight rules are driven through the
// held fake transport, so their order is exact. Every track value is invented.

/// A playing-now record of the invented track at `seconds` into it.
private func record(at seconds: Double, _ state: LsState = .playing) -> NowPlayingRecord {
  var info = AdditionalInfo()
  info.submissionClient = "scrobbler"
  info.submissionClientVersion = "0.1.0"
  info.lsPlayID = testPlayID
  info.lsPositionSeconds = seconds
  info.lsState = state
  info.lsMeasuredAt = 1_795_000_000 + seconds
  let metadata = TrackMetadata(
    artistName: "The Paper Lanterns", trackName: "Harbor Lights at Noon",
    releaseName: "Saltwater Almanac", additionalInfo: info)
  return NowPlayingRecord(
    listenType: .playingNow, payload: [NowPlayingItem(trackMetadata: metadata)])
}

/// The position each recorded call's body carries, in call order.
private func positions(_ calls: [FakeTransport.Call]) throws -> [Double?] {
  try calls.map {
    try RecordCoding.decode(NowPlayingRecord.self, from: $0.body).payload[0].trackMetadata
      .additionalInfo.lsPositionSeconds
  }
}

/// A sink over `transport`, the relay at its default port and the test token.
@MainActor private func makeSink(
  _ transport: any HTTPTransport,
  config: @escaping () throws -> ScrobblerConfig = { ScrobblerConfig() },
  token: @escaping () throws(TokenError) -> String = { testToken }
) -> NetworkNowPlayingSink {
  NetworkNowPlayingSink(transport: transport, config: config, token: token)
}

/// Publish `record` to `sink` and wait for every send it starts.
@MainActor private func publishAndSettle(_ sink: NetworkNowPlayingSink, _ record: NowPlayingRecord)
  async
{
  sink.publish(record)
  await sink.sending?.value
}

@Suite(.serialized) struct NetworkNowPlayingSinkTests {
  @MainActor @Test func aRecordIsPostedToTheRelayWithTheTokenAndJSON() async throws {
    let answer = Data(#"{"status":"ok"}"#.utf8)
    let server = try LoopbackServer(reply: .bytes(httpAnswer(status: 200, body: answer)))
    defer { server.stop() }
    let sink = makeSink(
      LoopbackTransport(timeout: NetworkNowPlayingSink.timeout),
      config: { ScrobblerConfig(relayPort: server.port) })
    let sent = record(at: 12.5)
    await publishAndSettle(sink, sent)
    let request = try #require(String(bytes: server.request, encoding: .utf8))
    #expect(request.hasPrefix("POST /1/submit-listens HTTP/1.1\r\n"))
    let lowered = request.lowercased()
    #expect(lowered.contains("\r\nauthorization: token \(testToken)\r\n"))
    #expect(lowered.contains("\r\ncontent-type: application/json\r\n"))
    let body = try #require(String(bytes: try RecordCoding.encode(sent), encoding: .utf8))
    #expect(request.hasSuffix("\r\n\r\n" + body))
    #expect(sink.sending == nil)
  }

  @MainActor @Test func theTimeoutIsTwoSeconds() {
    #expect(NetworkNowPlayingSink.timeout == 2)
  }

  @MainActor @Test func recordsPublishedDuringOneRequestSendOnlyTheNewest() async throws {
    let transport = FakeTransport()
    await transport.holdNextCall()
    let sink = makeSink(transport)
    sink.publish(record(at: 1))
    let sending = try #require(sink.sending)
    await transport.waitForCall()
    sink.publish(record(at: 2))
    sink.publish(record(at: 3))
    await transport.release()
    await sending.value
    let calls = await transport.calls
    #expect(try positions(calls) == [1, 3])
    #expect(calls.allSatisfy { $0.url == ScrobblerConfig().relayURL })
    #expect(calls.allSatisfy { $0.headers["Authorization"] == "Token \(testToken)" })
    #expect(calls.allSatisfy { $0.headers["Content-Type"] == "application/json" })
  }

  @MainActor
  @Test(arguments: [
    TransportResult.failed(reason: "URL error -1004"),
    .response(status: 503, body: Data()),
    .response(status: 401, body: Data()),
  ])
  func aFailedSendDropsTheRecord(answer: TransportResult) async throws {
    let transport = FakeTransport([answer])
    let sink = makeSink(transport)
    await publishAndSettle(sink, record(at: 1))
    await publishAndSettle(sink, record(at: 2))
    #expect(try positions(await transport.calls) == [1, 2])
  }

  @MainActor @Test func anUnreadableTokenSendsNothing() async {
    let transport = FakeTransport()
    let sink = makeSink(transport, token: { () throws(TokenError) -> String in throw .missing })
    await publishAndSettle(sink, record(at: 1))
    #expect(await transport.calls.isEmpty)
  }

  @MainActor @Test func aRefusedConfigSendsNothing() async {
    let transport = FakeTransport()
    let sink = makeSink(transport, config: { throw ConfigError.invalidValue(key: "relay_port") })
    await publishAndSettle(sink, record(at: 1))
    #expect(await transport.calls.isEmpty)
  }

  @MainActor @Test func theRelayPortFromTheConfigIsUsed() async {
    let transport = FakeTransport()
    let sink = makeSink(transport, config: { ScrobblerConfig(relayPort: 50001) })
    await publishAndSettle(sink, record(at: 1, .stopped))
    #expect(await transport.calls.map(\.url) == [ScrobblerConfig(relayPort: 50001).relayURL])
  }

  @MainActor @Test func theFanOutReachesEverySinkInOrder() {
    let first = RecordingSink()
    let second = StatusNowPlayingSink()
    let fanOut = FanOutNowPlayingSink([first, second])
    fanOut.publish(record(at: 1))
    fanOut.publish(record(at: 2))
    #expect(first.records == [record(at: 1), record(at: 2)])
    #expect(second.latest == record(at: 2))
  }
}

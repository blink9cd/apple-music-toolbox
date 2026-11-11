import Foundation
import Testing

@testable import ScrobblerCore

@MainActor @Test func aDrainSendsEveryFileInNameOrderAndRemovesIt() async throws {
  let rig = try Rig()
  let files = try rig.enqueue(3)
  let bodies = try files.map { try Data(contentsOf: $0) }
  #expect(await rig.drainer.drain() == .drained)
  let calls = await rig.transport.calls
  #expect(calls.map(\.body) == bodies)
  #expect(calls.allSatisfy { $0.url == ScrobblerConfig().submitURL })
  #expect(try rig.pendingNames().isEmpty)
  #expect(rig.drainer.lastSentAt == 1000)
  #expect(rig.drainer.lastError == nil)
  #expect(rig.drainer.nextAttemptAt == nil)
}

@MainActor @Test func theRequestCarriesTheTokenAndTheContentType() async throws {
  let rig = try Rig()
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  let headers = try #require(await rig.transport.calls.first).headers
  #expect(headers == ["Authorization": "Token \(testToken)", "Content-Type": "application/json"])
}

@MainActor @Test func theConfiguredPortIsUsed() async throws {
  let rig = try Rig()
  rig.configResult = { ScrobblerConfig(storePort: 50000) }
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  #expect(await rig.transport.calls.first?.url == ScrobblerConfig(storePort: 50000).submitURL)
}

@MainActor @Test(arguments: [400, 413])
func aRefusalMovesTheFileWithTheFindingsAndGoesOn(status: Int) async throws {
  let findings = Data(#"{"findings":["bad"]}"#.utf8)
  let rig = try Rig([.response(status: status, body: findings)])
  let files = try rig.enqueue(2)
  #expect(await rig.drainer.drain() == .drained)
  #expect(await rig.transport.calls.count == 2)
  #expect(try rig.queue.refusedCount() == 1)
  let stem = files[0].deletingPathExtension().lastPathComponent
  let sidecar = rig.queue.refusedDir.appendingPathComponent("\(stem).why.json")
  #expect(try Data(contentsOf: sidecar) == findings)
  #expect(try rig.pendingNames().isEmpty)
}

@MainActor
@Test(arguments: [
  (TransportResult.response(status: 401, body: Data()), "token refused"),
  (.response(status: 403, body: Data()), "store answered 403"),
  (.response(status: 404, body: Data()), "store answered 404"),
  (.response(status: 302, body: Data()), "store answered 302"),
  (.response(status: 503, body: Data()), "store unavailable"),
  (.failed(reason: "URL error -1004"), "store unreachable"),
])
func aKeepAnswerKeepsTheFileAndStops(answer: TransportResult, error: String) async throws {
  let rig = try Rig([answer])
  let files = try rig.enqueue(2)
  #expect(await rig.drainer.drain() == .stopped(error: error))
  #expect(await rig.transport.calls.count == 1)
  #expect(try rig.pendingNames() == files.map(\.lastPathComponent))
  #expect(rig.drainer.lastError == error)
  #expect(rig.drainer.nextAttemptAt == 1005)
  #expect(try rig.queue.refusedCount() == 0)
}

@MainActor
@Test(arguments: [
  TransportResult.failed(reason: "down"), .response(status: 401, body: Data()),
  .response(status: 503, body: Data()),
])
func theBackOffGrowsThenHoldsAndASuccessResetsIt(failure: TransportResult) async throws {
  let rig = try Rig(
    Array(repeating: failure, count: 5) + [.response(status: 200, body: Data()), failure])
  try rig.enqueue(1)
  var waits: [Double] = []
  for _ in 0..<5 {
    _ = await rig.drainer.drain()
    let next = try #require(rig.drainer.nextAttemptAt)
    waits.append(next - rig.now)
    rig.now = next
  }
  #expect(waits == [5, 15, 60, 300, 300])
  #expect(await rig.drainer.drain() == .drained)
  #expect(rig.drainer.nextAttemptAt == nil)
  #expect(rig.drainer.lastError == nil)
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  #expect(rig.drainer.nextAttemptAt == rig.now + 5)
}

@MainActor @Test func aDrainWhileBackingOffSendsNothing() async throws {
  let rig = try Rig([.failed(reason: "down")])
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  rig.now += 4
  #expect(await rig.drainer.drain() == .idle)
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.tokenReads == 1)
}

@MainActor @Test func anEmptyQueueIsIdleAndReadsNoToken() async throws {
  let rig = try Rig()
  #expect(await rig.drainer.drain() == .idle)
  #expect(rig.tokenReads == 0)
  #expect(await rig.transport.calls.isEmpty)
}

@MainActor @Test func theTokenIsReadAfreshOnEveryDrain() async throws {
  let rig = try Rig()
  try rig.enqueue(2)
  _ = await rig.drainer.drain()
  #expect(rig.tokenReads == 1)
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  #expect(rig.tokenReads == 2)
}

@MainActor @Test func anUnreadableTokenStopsBeforeAnyRequest() async throws {
  let rig = try Rig()
  rig.tokenResult = .failure(.tooOpen)
  try rig.enqueue(1)
  #expect(await rig.drainer.drain() == .stopped(error: "token unreadable: tooOpen"))
  #expect(await rig.transport.calls.isEmpty)
  #expect(try rig.pendingNames().count == 1)
  #expect(rig.drainer.lastError == "token unreadable: tooOpen")
  #expect(!(rig.drainer.lastError ?? "").contains(testToken))
}

@MainActor @Test func aRefusedConfigStopsBeforeAnyRequest() async throws {
  let rig = try Rig()
  rig.configResult = { throw ConfigError.invalidValue(key: "store_port") }
  try rig.enqueue(1)
  #expect(await rig.drainer.drain() == .stopped(error: "config refused: store_port"))
  #expect(await rig.transport.calls.isEmpty)
  #expect(rig.tokenReads == 0)
}

@MainActor @Test func anyOtherConfigFailureIsRefusedAsTheWholeFile() async throws {
  let rig = try Rig()
  rig.configResult = { throw CocoaError(.fileReadUnknown) }
  try rig.enqueue(1)
  #expect(await rig.drainer.drain() == .stopped(error: "config refused: \(ConfigError.wholeFile)"))
}

@MainActor @Test func aQueueThatCannotBeListedStops() async throws {
  let rig = try Rig()
  try rig.enqueue(1)
  try setMode(0o000, of: rig.queue.queueDir)
  defer { try? setMode(0o700, of: rig.queue.queueDir) }
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.isEmpty)
}

@MainActor @Test func aFileThatCannotBeReadIsSkippedAndReported() async throws {
  let rig = try Rig()
  let files = try rig.enqueue(2)
  let readable = try Data(contentsOf: files[1])
  try setMode(0o000, of: files[0])
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.map(\.body) == [readable])
  #expect(try rig.pendingNames() == [files[0].lastPathComponent])
  #expect(rig.drainer.lastError == "queue unreadable")
  #expect(rig.drainer.nextAttemptAt == nil)
}

@MainActor @Test(arguments: [200, 400])
func aQueueThatCannotBeChangedStopsAndBacksOff(status: Int) async throws {
  let rig = try Rig([.response(status: status, body: Data())])
  try rig.enqueue(2)
  try setMode(0o500, of: rig.queue.queueDir)
  defer { try? setMode(0o700, of: rig.queue.queueDir) }
  #expect(await rig.drainer.drain() == .stopped(error: "queue unwritable"))
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.drainer.nextAttemptAt == 1005)
}

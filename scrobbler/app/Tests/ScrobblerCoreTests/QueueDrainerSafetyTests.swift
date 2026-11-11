import Foundation
import Testing

@testable import ScrobblerCore

@MainActor @Test func aSecondDrainWhileOneIsSendingIsIdle() async throws {
  let rig = try Rig()
  try rig.enqueue(1)
  await rig.transport.holdNextCall()
  let first = Task { await rig.drainer.drain() }
  await rig.transport.waitForCall()
  #expect(await rig.drainer.drain() == .idle)
  await rig.transport.release()
  #expect(await first.value == .drained)
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.drainer.lastError == nil)
}

@MainActor @Test func aFileGoneBeforeItsAcceptanceStillCountsAsSent() async throws {
  let rig = try Rig()
  let path = try rig.enqueue(1)[0].path
  await rig.transport.setBeforeAnswer { _ in unlink(path) }
  #expect(await rig.drainer.drain() == .drained)
  #expect(rig.drainer.lastError == nil)
  #expect(rig.drainer.lastSentAt == 1000)
}

@MainActor @Test func aFileGoneBeforeItIsReadIsNotAnError() async throws {
  let rig = try Rig()
  let files = try rig.enqueue(2)
  let laterPath = files[1].path
  await rig.transport.setBeforeAnswer { _ in unlink(laterPath) }
  #expect(await rig.drainer.drain() == .drained)
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.drainer.lastError == nil)
}

@MainActor @Test func aStopWithoutBackOffClearsAPastWait() async throws {
  let rig = try Rig([.failed(reason: "down")])
  try rig.enqueue(1)
  _ = await rig.drainer.drain()
  rig.now = try #require(rig.drainer.nextAttemptAt) + 1
  rig.tokenResult = .failure(.missing)
  #expect(await rig.drainer.drain() == .stopped(error: "token unreadable: missing"))
  #expect(rig.drainer.nextAttemptAt == nil)
}

@MainActor @Test func aSymlinkInTheQueueIsNotFollowed() async throws {
  let rig = try Rig()
  let good = try rig.enqueue(1)[0]
  let outside = rig.temp.child("outside.json")
  try FileManager.default.copyItem(at: good, to: outside)
  try FileManager.default.createSymbolicLink(
    at: rig.earlyName(1), withDestinationURL: outside)
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.map(\.body) == [try Data(contentsOf: outside)])
  #expect(rig.drainer.nextAttemptAt == nil)
}

@MainActor @Test func anOversizeFileInTheQueueIsNotSent() async throws {
  let rig = try Rig()
  try rig.enqueue(1)
  try FileManager.default.createDirectory(at: rig.queue.queueDir, withIntermediateDirectories: true)
  try Data(repeating: UInt8(ascii: "x"), count: 1_048_576).write(to: rig.earlyName(1))
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.count == 1)
  #expect(try rig.pendingNames().count == 1)
}

@MainActor @Test func aRefusalWhoseAnswerIsNotAJSONObjectGetsTheFixedFindings() async throws {
  let body = Data([0x1B]) + Data("[31mnot json".utf8)
  let rig = try Rig([.response(status: 400, body: body)])
  let file = try rig.enqueue(1)[0]
  #expect(await rig.drainer.drain() == .drained)
  let stem = file.deletingPathExtension().lastPathComponent
  let sidecar = rig.queue.refusedDir.appendingPathComponent("\(stem).why.json")
  #expect(try Data(contentsOf: sidecar) == Data(#"{"findings":["store answer unreadable"]}"#.utf8))
}

@MainActor @Test func aFIFOInTheQueueIsNotReadAndDoesNotBlock() async throws {
  let rig = try Rig()
  try rig.enqueue(1)
  #expect(mkfifo(rig.earlyName(1).path, 0o600) == 0)
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.count == 1)
}

@MainActor @Test func aRecordAtTheCapIsSentAndOneOverIsNot() async throws {
  let rig = try Rig()
  try FileManager.default.createDirectory(at: rig.queue.queueDir, withIntermediateDirectories: true)
  try Data(repeating: 0x20, count: QueueStore.maxRecordBytes).write(to: rig.earlyName(1))
  try Data(repeating: 0x20, count: QueueStore.maxRecordBytes + 1).write(to: rig.earlyName(2))
  #expect(await rig.drainer.drain() == .stopped(error: "queue unreadable"))
  #expect(await rig.transport.calls.map(\.body.count) == [QueueStore.maxRecordBytes])
}

@MainActor @Test func aRefusalWhoseAnswerIsAJSONArrayGetsTheFixedFindings() async throws {
  let rig = try Rig([.response(status: 413, body: Data("[1]".utf8))])
  let file = try rig.enqueue(1)[0]
  _ = await rig.drainer.drain()
  let stem = file.deletingPathExtension().lastPathComponent
  let sidecar = rig.queue.refusedDir.appendingPathComponent("\(stem).why.json")
  #expect(try Data(contentsOf: sidecar) == Data(#"{"findings":["store answer unreadable"]}"#.utf8))
}

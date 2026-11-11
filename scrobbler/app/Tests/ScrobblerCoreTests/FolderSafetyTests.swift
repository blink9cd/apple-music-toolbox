import Foundation
import Testing

@testable import ScrobblerCore

/// A queue in a temp folder, with its two folders not yet made.
private func makeQueue() throws -> (TempFolder, QueueStore) {
  let temp = try TempFolder()
  return (temp, QueueStore(queueDir: temp.child("queue"), refusedDir: temp.child("refused")))
}

/// A stand-in for the engine's open play.
private struct SavedPlay: Codable, Equatable {
  var playID: String
  var padding = ""
}

@Test func aFolderNamedLikeARecordIsNotPending() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  let folder = queue.queueDir.appendingPathComponent("1700000000-\(testPlayID)-001.json")
  try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
  #expect(try queue.pending() == [file])
  _ = temp
}

@Test func removingAFileAlreadyGoneIsFine() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  try queue.remove(file)
  try queue.remove(file)
  #expect(try queue.pending().isEmpty)
  _ = temp
}

@Test func removeNeverDeletesAFolder() throws {
  let (temp, queue) = try makeQueue()
  try queue.enqueue(try queuedListen())
  let folder = queue.queueDir.appendingPathComponent("1700000000-\(testPlayID)-001.json")
  try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
  try writeFile("x", to: folder.appendingPathComponent("inside"))
  #expect(throws: FileIOError.self) { try queue.remove(folder) }
  #expect(FileManager.default.fileExists(atPath: folder.appendingPathComponent("inside").path))
  _ = temp
}

@Test func aQueueFolderOthersCanReadIsRefused() throws {
  let (temp, queue) = try makeQueue()
  try FileManager.default.createDirectory(at: queue.queueDir, withIntermediateDirectories: false)
  try setMode(0o755, of: queue.queueDir)
  #expect(throws: FileIOError.self) { try queue.enqueue(try queuedListen()) }
  #expect(try names(in: queue.queueDir).isEmpty)
  _ = temp
}

@Test func aSymlinkedQueueFolderIsRefused() throws {
  let temp = try TempFolder()
  let real = temp.child("real")
  try FileManager.default.createDirectory(at: real, withIntermediateDirectories: false)
  try setMode(0o700, of: real)
  let link = temp.child("queue")
  try FileManager.default.createSymbolicLink(at: link, withDestinationURL: real)
  let queue = QueueStore(queueDir: link, refusedDir: temp.child("refused"))
  #expect(throws: FileIOError.self) { try queue.enqueue(try queuedListen()) }
  #expect(try names(in: real).isEmpty)
}

@Test func aSymlinkedOpenPlayIsNotRead() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try state.writeOpenPlay(SavedPlay(playID: testPlayID))
  let outside = temp.child("outside.json")
  try FileManager.default.moveItem(at: state.openPlayFile, to: outside)
  try FileManager.default.createSymbolicLink(at: state.openPlayFile, withDestinationURL: outside)
  #expect(state.readOpenPlay(SavedPlay.self) == nil)
}

@Test func anOversizeOpenPlayIsNotRead() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  let padding = String(repeating: "x", count: StateFiles.maxOpenPlayBytes)
  try state.writeOpenPlay(SavedPlay(playID: testPlayID, padding: padding))
  #expect(state.readOpenPlay(SavedPlay.self) == nil)
}

@Test func aFIFOAtTheOpenPlayIsNotReadAndDoesNotBlock() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try FileManager.default.createDirectory(
    at: temp.child("state"), withIntermediateDirectories: true)
  #expect(mkfifo(state.openPlayFile.path, 0o600) == 0)
  #expect(state.readOpenPlay(SavedPlay.self) == nil)
}

@Test func theListenTimeIsReadBackFromTheName() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen(listenedAt: 1_795_000_123)).file
  #expect(QueueStore.listenedAt(of: file) == 1_795_000_123)
  let early = try queue.enqueue(try queuedListen(listenedAt: 42)).file
  #expect(QueueStore.listenedAt(of: early) == 42)
  _ = temp
}

@Test(arguments: [
  "notes.json", "17950001-\(testPlayID)-001.json", "179500000a-\(testPlayID)-001.json",
  ".tmp-1795000000", "1795000000-\(testPlayID)-001.why.json", "1795000000",
  "1795000000_\(testPlayID)-001.json",
])
func aNameThatIsNotARecordHasNoListenTime(name: String) {
  let url = URL(fileURLWithPath: "/queue-for-test").appendingPathComponent(name)
  #expect(QueueStore.listenedAt(of: url) == nil)
}

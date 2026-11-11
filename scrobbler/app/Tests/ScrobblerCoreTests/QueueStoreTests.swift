import Foundation
import Testing

@testable import ScrobblerCore

/// A queue in a temp folder, with its two folders not yet made.
private func makeQueue() throws -> (TempFolder, QueueStore) {
  let temp = try TempFolder()
  return (temp, QueueStore(queueDir: temp.child("queue"), refusedDir: temp.child("refused")))
}

@Test func theListenLimitIsTheContractsListenLimit() throws {
  #expect(try contractDefaults()["max_listen_size"] as? Int == QueueStore.storeListenLimit)
}

@Test func theFileNameIsTimePlayAndPiece() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen(listenedAt: 1_795_000_000, piece: 2)).file
  #expect(file.lastPathComponent == "1795000000-\(testPlayID)-002.json")
  #expect(
    file.deletingLastPathComponent().standardizedFileURL == queue.queueDir.standardizedFileURL)
  _ = temp
}

@Test func theTimeIsPaddedToTenDigits() throws {
  #expect(
    try QueueStore.fileName(for: try queuedListen(listenedAt: 42, piece: 999))
      == "0000000042-\(testPlayID)-999.json")
}

@Test func theWrittenBytesAreTheRecordsEncoding() throws {
  let (temp, queue) = try makeQueue()
  let record = try queuedListen()
  let file = try queue.enqueue(record).file
  #expect(try Data(contentsOf: file) == (try RecordCoding.encode(record)))
  _ = temp
}

@Test func theWriteLeavesNoTempFileAndIsPrivate() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  #expect(try names(in: queue.queueDir) == [file.lastPathComponent])
  let mode = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions]
  #expect(mode as? Int == 0o600)
  _ = temp
}

@Test func aFailedRenameLeavesNoTempFile() throws {
  let (temp, queue) = try makeQueue()
  let record = try queuedListen()
  let name = try QueueStore.fileName(for: record)
  try FileManager.default.createDirectory(
    at: queue.queueDir.appendingPathComponent(name), withIntermediateDirectories: true)
  #expect(throws: FileIOError.self) { try queue.enqueue(record) }
  #expect(try names(in: queue.queueDir) == [name])
  _ = temp
}

@Test func aRecordWithoutAPartIsRefused() throws {
  #expect(throws: QueueError.missingNamePart("ls_play_id")) {
    try QueueStore.fileName(for: try queuedListen(playID: nil))
  }
  #expect(throws: QueueError.missingNamePart("ls_piece")) {
    try QueueStore.fileName(for: try queuedListen(piece: nil))
  }
}

@Test func aPartOutsideTheNameRuleIsRefused() throws {
  #expect(throws: QueueError.invalidNamePart("ls_play_id")) {
    try QueueStore.fileName(for: try queuedListen(playID: "../../escape"))
  }
  #expect(throws: QueueError.invalidNamePart("ls_play_id")) {
    try QueueStore.fileName(for: try queuedListen(playID: testPlayID.uppercased()))
  }
  #expect(throws: QueueError.invalidNamePart("ls_piece")) {
    try QueueStore.fileName(for: try queuedListen(piece: 1000))
  }
  #expect(throws: QueueError.invalidNamePart("ls_piece")) {
    try QueueStore.fileName(for: try queuedListen(piece: 0))
  }
  #expect(throws: QueueError.invalidNamePart("listened_at")) {
    try QueueStore.fileName(for: try queuedListen(listenedAt: -1))
  }
  #expect(throws: QueueError.invalidNamePart("listened_at")) {
    try QueueStore.fileName(for: try queuedListen(listenedAt: 10_000_000_000))
  }
}

@Test func onlyOneSingleListenIsQueued() throws {
  var batch = try queuedListen()
  batch.listenType = .import
  #expect(throws: QueueError.notASingleListen) { try QueueStore.fileName(for: batch) }
  var double = try queuedListen()
  double.payload.append(double.payload[0])
  #expect(throws: QueueError.notASingleListen) { try QueueStore.fileName(for: double) }
}

@Test func pendingIsSortedByName() throws {
  let (temp, queue) = try makeQueue()
  let late = try queue.enqueue(try queuedListen(listenedAt: 1_795_000_100, piece: 1)).file
  let early = try queue.enqueue(try queuedListen(listenedAt: 1_795_000_000, piece: 3)).file
  let middle = try queue.enqueue(try queuedListen(listenedAt: 1_795_000_000, piece: 4)).file
  try writeFile("x", to: queue.queueDir.appendingPathComponent(".tmp-stray"))
  try writeFile("x", to: queue.queueDir.appendingPathComponent("notes.txt"))
  #expect(
    try queue.pending().map(\.lastPathComponent) == [early, middle, late].map(\.lastPathComponent))
  _ = temp
}

@Test func anAbsentQueueHasNothingPending() throws {
  let (temp, queue) = try makeQueue()
  #expect(try queue.pending().isEmpty)
  #expect(try queue.refusedCount() == 0)
  _ = temp
}

@Test func removeDeletesTheFile() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  try queue.remove(file)
  #expect(try queue.pending().isEmpty)
  _ = temp
}

@Test func refuseMovesTheFileAndWritesTheFindings() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  let findings = Data(#"{"findings":["x"]}"#.utf8)
  try queue.refuse(file, findings: findings)
  #expect(try queue.pending().isEmpty)
  let stem = file.deletingPathExtension().lastPathComponent
  #expect(try names(in: queue.refusedDir) == [file.lastPathComponent, "\(stem).why.json"])
  let sidecar = queue.refusedDir.appendingPathComponent("\(stem).why.json")
  #expect(try Data(contentsOf: sidecar) == findings)
  #expect(try queue.refusedCount() == 1)
  _ = temp
}

@Test func refuseFailsWhenTheQueueCannotBeChanged() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  try setMode(0o500, of: queue.queueDir)
  defer { try? setMode(0o700, of: queue.queueDir) }
  #expect(throws: FileIOError.self) { try queue.refuse(file, findings: Data()) }
  _ = temp
}

@Test func theQueueFoldersArePrivate() throws {
  let (temp, queue) = try makeQueue()
  let file = try queue.enqueue(try queuedListen()).file
  try queue.refuse(file, findings: Data())
  for folder in [queue.queueDir, queue.refusedDir] {
    let mode = try FileManager.default.attributesOfItem(atPath: folder.path)[.posixPermissions]
    #expect(mode as? Int == 0o700)
  }
  _ = temp
}

/// Invented text exactly `FieldText.maxTextBytes` long, the longest field a snapshot keeps.
let longestField = String(repeating: "Lantern ", count: FieldText.maxTextBytes / 8)

/// A listen whose text fields are each as long as a snapshot keeps, so its encoding is
/// larger than the queue reads back.
private func oversizedListen() throws -> ListenRecord {
  var record = try queuedListen()
  record.payload[0].trackMetadata.artistName = longestField
  record.payload[0].trackMetadata.trackName = longestField
  record.payload[0].trackMetadata.releaseName = longestField
  record.payload[0].trackMetadata.additionalInfo.lsComposer = longestField
  return record
}

/// The fixed findings beside a record too large for the queue.
let oversizedFindings = #"{"findings":["record larger than the store's per-listen limit"]}"#

@Test func aRecordLargerThanTheCapGoesStraightToRefused() throws {
  let (temp, queue) = try makeQueue()
  let record = try oversizedListen()
  #expect(try RecordCoding.encode(record).count > QueueStore.maxRecordBytes)
  let name = try QueueStore.fileName(for: record)
  let refused = queue.refusedDir.appendingPathComponent(name)
  let written = try queue.enqueue(record)
  #expect(written == .refused(refused))
  #expect(written.file == refused)
  #expect(try queue.pending().isEmpty)
  #expect(try queue.refusedCount() == 1)
  let stem = String(name.dropLast(QueueStore.recordSuffix.count))
  #expect(try names(in: queue.refusedDir) == [name, "\(stem).why.json"])
  let sidecar = queue.refusedDir.appendingPathComponent("\(stem).why.json")
  #expect(try Data(contentsOf: sidecar) == Data(oversizedFindings.utf8))
  #expect(try Data(contentsOf: refused) == (try RecordCoding.encode(record)))
  let mode = try FileManager.default.attributesOfItem(atPath: queue.refusedDir.path)[
    .posixPermissions]
  #expect(mode as? Int == 0o700)
  _ = temp
}

@Test func anOversizedRecordsFindingsAreWrittenBeforeTheRecord() throws {
  let (temp, queue) = try makeQueue()
  let record = try oversizedListen()
  let name = try QueueStore.fileName(for: record)
  try FileIO.makeFolder(queue.refusedDir)
  try FileManager.default.createDirectory(
    at: queue.refusedDir.appendingPathComponent(name), withIntermediateDirectories: false)
  #expect(throws: FileIOError.self) { try queue.enqueue(record) }
  let stem = String(name.dropLast(QueueStore.recordSuffix.count))
  #expect(try names(in: queue.refusedDir) == [name, "\(stem).why.json"])
  #expect(try queue.pending().isEmpty)
  _ = temp
}

@Test func aRecordExactlyAtTheCapIsQueued() throws {
  let (temp, queue) = try makeQueue()
  var record = try queuedListen()
  let short = QueueStore.maxRecordBytes - (try RecordCoding.encode(record)).count
  record.payload[0].trackMetadata.trackName += String(repeating: "x", count: short)
  #expect(try RecordCoding.encode(record).count == QueueStore.maxRecordBytes)
  let queued = queue.queueDir.appendingPathComponent(try QueueStore.fileName(for: record))
  #expect(try queue.enqueue(record) == .queued(queued))
  #expect(try queue.pending().count == 1)
  #expect(try queue.refusedCount() == 0)
  _ = temp
}

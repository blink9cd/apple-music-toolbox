import Foundation
import Testing

@testable import ScrobblerCore

/// A stand-in for the engine's open play: any Codable value round-trips.
private struct SamplePlay: Codable, Equatable {
  var playID: String
  var seconds: Int
}

/// The keys `status.json` carries, each one exactly once.
private let statusKeys: Set<String> = [
  "format", "version", "pid", "started_at", "heartbeat_at", "music_running", "playing",
  "queue_backlog", "oldest_queued_at", "refused_count", "last_queued_at", "last_sent_at",
  "last_send_error", "unrecordable_count", "automation_denied", "now_playing",
]

@Test func theStateFilesSitWhereThePathsSay() {
  let paths = ScrobblerPaths(home: URL(fileURLWithPath: "/home-for-test", isDirectory: true))
  let state = StateFiles(stateDir: paths.stateDir)
  #expect(state.statusFile == paths.statusFile)
  #expect(state.openPlayFile == paths.openPlayFile)
}

@Test func aNewStatusWritesEveryKeyWithNullsForTheUnknown() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try state.writeStatus(
    StatusSnapshot(pid: 4242, startedAt: 1_793_000_000, heartbeatAt: 1_793_000_030))
  let object = try parsedDictionary(Data(contentsOf: state.statusFile))
  #expect(Set(object.allKeys.compactMap { $0 as? String }) == statusKeys)
  #expect(object["format"] as? Int == 1)
  #expect(object["version"] as? String == Layout.version)
  #expect(object["pid"] as? Int == 4242)
  #expect(object["heartbeat_at"] as? Double == 1_793_000_030)
  for key in [
    "oldest_queued_at", "last_queued_at", "last_sent_at", "last_send_error", "now_playing",
  ] {
    #expect(object[key] is NSNull, "\(key) should be null")
  }
  #expect(try names(in: state.statusFile.deletingLastPathComponent()) == ["status.json"])
}

@Test func aFullStatusRoundTrips() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  var status = StatusSnapshot(pid: 7, startedAt: 1, heartbeatAt: 2)
  status.musicRunning = true
  status.playing = true
  status.queueBacklog = 3
  status.oldestQueuedAt = 1_795_000_000
  status.refusedCount = 1
  status.lastQueuedAt = 1_795_000_100
  status.lastSentAt = 1_795_000_050.5
  status.lastSendError = "store unreachable"
  status.unrecordableCount = 2
  status.automationDenied = true
  status.nowPlaying = try RecordCoding.decode(
    NowPlayingRecord.self, from: sampleData("valid", "playing-now-local-file.json"))
  try state.writeStatus(status)
  let back = try RecordCoding.decode(StatusSnapshot.self, from: Data(contentsOf: state.statusFile))
  #expect(back == status)
}

@Test func aStatusIntoAFolderThatCannotBeWrittenThrows() throws {
  let temp = try TempFolder()
  let folder = temp.child("state")
  try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
  try setMode(0o500, of: folder)
  defer { try? setMode(0o700, of: folder) }
  let state = StateFiles(stateDir: folder)
  #expect(throws: FileIOError.self) {
    try state.writeStatus(StatusSnapshot(pid: 1, startedAt: 1, heartbeatAt: 1))
  }
}

@Test func theOpenPlayRoundTripsAndNilDeletesIt() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  #expect(state.readOpenPlay(SamplePlay.self) == nil)
  let play = SamplePlay(playID: testPlayID, seconds: 40)
  try state.writeOpenPlay(play)
  #expect(state.readOpenPlay(SamplePlay.self) == play)
  try state.writeOpenPlay(SamplePlay?.none)
  #expect(state.readOpenPlay(SamplePlay.self) == nil)
  #expect(!FileManager.default.fileExists(atPath: state.openPlayFile.path))
  try state.writeOpenPlay(SamplePlay?.none)
}

@Test func anUnreadableOpenPlayIsNil() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try FileManager.default.createDirectory(
    at: temp.child("state"), withIntermediateDirectories: true)
  try writeFile("{not json", to: state.openPlayFile)
  #expect(state.readOpenPlay(SamplePlay.self) == nil)
}

@Test func deletingTheOpenPlayInAFolderThatCannotBeWrittenThrows() throws {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try state.writeOpenPlay(SamplePlay(playID: testPlayID, seconds: 1))
  try setMode(0o500, of: temp.child("state"))
  defer { try? setMode(0o700, of: temp.child("state")) }
  #expect(throws: FileIOError.self) { try state.writeOpenPlay(SamplePlay?.none) }
}

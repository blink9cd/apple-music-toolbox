import Foundation
import Testing

@testable import ScrobblerCore

// The status files the app writes, kept as golden files that the Python status test reads
// with its own parser, so a key renamed on either side fails a test on that side.

/// The golden folder, `status_built/` beside the package.
private let statusBuiltDir = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
  .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
  .appendingPathComponent("status_built")
/// Set to "1" to write the golden files from the snapshots below instead of comparing.
private let regold = ProcessInfo.processInfo.environment["SCROBBLER_REGOLD"] == "1"

/// A snapshot with every field set, each to an invented value no other field shares.
private func everyFieldSet() throws -> StatusSnapshot {
  var status = StatusSnapshot(pid: 5150, startedAt: 1_795_000_000.5, heartbeatAt: 1_795_000_600.25)
  status.version = "9.8.7"
  status.musicRunning = true
  status.playing = true
  status.queueBacklog = 3
  status.oldestQueuedAt = 1_794_999_000
  status.refusedCount = 2
  status.lastQueuedAt = 1_795_000_500.75
  status.lastSentAt = 1_795_000_400
  status.lastSendError = "store unreachable"
  status.unrecordableCount = 4
  status.automationDenied = true
  status.nowPlaying = try RecordCoding.decode(NowPlayingRecord.self, from: minimalNowPlaying())
  return status
}

/// A snapshot of a fresh start: every optional field unknown, so written as null.
private func optionalsNull() -> StatusSnapshot {
  var status = StatusSnapshot(pid: 6160, startedAt: 1_795_100_000, heartbeatAt: 1_795_100_030)
  status.version = "9.8.7"
  return status
}

/// The bytes the status writer puts in `status.json` for `status`.
private func writtenBytes(of status: StatusSnapshot) throws -> Data {
  let temp = try TempFolder()
  let state = StateFiles(stateDir: temp.child("state"))
  try state.writeStatus(status)
  return try Data(contentsOf: state.statusFile)
}

/// Each golden file's name and the bytes its snapshot is written as.
private func goldenStatuses() throws -> [(name: String, bytes: Data)] {
  [
    ("status-every-field.json", try writtenBytes(of: try everyFieldSet())),
    ("status-optionals-null.json", try writtenBytes(of: optionalsNull())),
  ]
}

@Test func theGoldenStatusFilesMatchTheWriter() throws {
  let statuses = try goldenStatuses()
  for status in statuses {
    let url = statusBuiltDir.appendingPathComponent(status.name)
    if regold {
      try FileManager.default.createDirectory(at: statusBuiltDir, withIntermediateDirectories: true)
      try status.bytes.write(to: url, options: .atomic)
    } else {
      #expect(try Data(contentsOf: url) == status.bytes, "\(status.name)")
    }
  }
  let present = try FileManager.default.contentsOfDirectory(atPath: statusBuiltDir.path).sorted()
  #expect(present == statuses.map(\.name).sorted())
}

@Test func theGoldenStatusFilesDecodeToTheirSnapshots() throws {
  for status in [try everyFieldSet(), optionalsNull()] {
    #expect(
      try RecordCoding.decode(StatusSnapshot.self, from: try writtenBytes(of: status)) == status)
  }
}

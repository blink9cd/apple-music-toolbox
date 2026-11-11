import Foundation
import Testing

@testable import ScrobblerCore

/// The golden folder, `contract_built/` beside the contract copy, which the Python contract
/// test validates against the copied schemas.
private let builtDir = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
  .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
  .appendingPathComponent("contract_built")
/// Set to "1" to write the golden files from the records below instead of comparing.
private let regold = ProcessInfo.processInfo.environment["SCROBBLER_REGOLD"] == "1"

/// The track every golden play is of; every value is invented.
private func lanternInfo() -> AdditionalInfo {
  var info = AdditionalInfo()
  info.submissionClient = "scrobbler"
  info.submissionClientVersion = "0.1.0"
  info.mediaPlayer = "Music"
  info.durationMs = 263_000
  info.lsSource = .localFile
  info.lsMediaType = .music
  info.lsFilePath = "/Volumes/Archive/Music/Glasshouse Orchard/Weather Diary/05 Third Lantern.m4a"
  info.lsPersistentID = "5E6F708192A3B4C5"
  info.lsPlayID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
  return info
}

/// Every Music.app field read when a play starts, set on `info`.
private func addMusicAppFields(to info: inout AdditionalInfo) {
  info.lsComposer = "Invented Composer"
  info.lsTrackCount = 11
  info.lsDiscCount = 2
  info.lsCompilation = false
  info.lsBpm = 96
  info.lsGrouping = "Orchard Suite"
  info.lsWork = "Weather Diary, Book Two"
  info.lsMovement = "Third Lantern"
  info.lsMovementNumber = 3
  info.lsMovementCount = 5
  info.lsMusicRating = 60
  info.lsMusicFavorited = true
  info.lsMusicDisliked = false
  info.lsMusicAlbumFavorited = true
  info.lsMusicAlbumDisliked = false
  info.lsKind = "Apple Lossless audio file"
  info.lsBitRate = 1_024
  info.lsSampleRate = 48_000
  info.lsMusicDateAdded = 1_760_000_000
  info.lsMusicPlayedCount = 7
  info.lsMusicSkippedCount = 2
  info.lsMusicPlayedDate = 1_794_000_000
}

/// A local-file play carrying every field the scrobbler writes.
private func localFileEveryField() -> ListenRecord {
  var info = lanternInfo()
  info.tracknumber = "5"
  info.durationPlayed = 251
  info.lsPiece = 1
  info.lsAlbumArtist = "Glasshouse Orchard"
  info.lsDiscNumber = 2
  info.lsGenre = "Chamber Pop"
  info.lsYear = 2_022
  addMusicAppFields(to: &info)
  let metadata = TrackMetadata(
    artistName: "Glasshouse Orchard", trackName: "Third Lantern", releaseName: "Weather Diary",
    additionalInfo: info)
  return ListenRecord(
    listenType: .single, payload: [Listen(listenedAt: 1_795_001_200, trackMetadata: metadata)])
}

/// A radio play with only the keys a listen must carry, and its source.
private func radioMinimal() -> ListenRecord {
  var info = AdditionalInfo()
  info.submissionClient = "scrobbler"
  info.submissionClientVersion = "0.1.0"
  info.durationPlayed = 140
  info.lsSource = .radio
  let metadata = TrackMetadata(
    artistName: "Lighthouse Relay", trackName: "Fog Signal Hour", additionalInfo: info)
  return ListenRecord(
    listenType: .single, payload: [Listen(listenedAt: 1_795_003_600, trackMetadata: metadata)])
}

/// The local-file track paused partway through, played a little fast.
private func playingNowPaused() -> NowPlayingRecord {
  var info = lanternInfo()
  info.lsPositionSeconds = 97.25
  info.lsState = .paused
  info.lsRate = 1.25
  info.lsMeasuredAt = 1_795_001_297.25
  let metadata = TrackMetadata(
    artistName: "Glasshouse Orchard", trackName: "Third Lantern", releaseName: "Weather Diary",
    additionalInfo: info)
  return NowPlayingRecord(
    listenType: .playingNow, payload: [NowPlayingItem(trackMetadata: metadata)])
}

/// The record the engine itself sends when Music quits partway through a play of the
/// engine tests' invented track, read in full by its snapshot.
private func playingNowStopped() throws -> NowPlayingRecord {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.snapshot(snapshot(), at: base + 100))
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let records = engine.handle(.musicQuit(at: base + 105)).compactMap { effect in
    guard case .nowPlaying(let record) = effect else { return nil as NowPlayingRecord? }
    return record
  }
  return try #require(records.first)
}

/// Each golden file's name and the bytes its record encodes to.
private func goldenRecords() throws -> [(name: String, bytes: Data)] {
  [
    ("single-local-file-every-field.json", try RecordCoding.encode(localFileEveryField())),
    ("single-radio-minimal.json", try RecordCoding.encode(radioMinimal())),
    ("playing-now-paused.json", try RecordCoding.encode(playingNowPaused())),
    ("playing-now-stopped.json", try RecordCoding.encode(try playingNowStopped())),
  ]
}

@Test func theGoldenRecordsMatchTheirFiles() throws {
  let records = try goldenRecords()
  for record in records {
    let url = builtDir.appendingPathComponent(record.name)
    if regold {
      try FileManager.default.createDirectory(at: builtDir, withIntermediateDirectories: true)
      try record.bytes.write(to: url, options: .atomic)
    } else {
      #expect(try Data(contentsOf: url) == record.bytes, "\(record.name)")
    }
  }
  let present = try FileManager.default.contentsOfDirectory(atPath: builtDir.path).sorted()
  #expect(present == records.map(\.name).sorted())
}

@Test func theGoldenRecordsDecodeToThemselves() throws {
  #expect(
    try RecordCoding.decode(ListenRecord.self, from: RecordCoding.encode(localFileEveryField()))
      == localFileEveryField())
  #expect(
    try RecordCoding.decode(NowPlayingRecord.self, from: RecordCoding.encode(playingNowPaused()))
      == playingNowPaused())
}

import Foundation
import Testing

@testable import ScrobblerCore

/// One snapshot result line: every field empty except those given.
private func snapshotLine(_ values: [SnapshotField: String]) -> String {
  SnapshotField.allCases.map { values[$0] ?? "" }
    .joined(separator: String(MusicScripts.separator))
}

/// The zone the fixed dates below are written in.
private let utc = TimeZone(identifier: "UTC") ?? .gmt

/// An invented track with every field filled.
private let fullTrack: [SnapshotField: String] = [
  .persistentID: "0a1b2c3d4e5f6071", .trackClass: "file track",
  .location: "/Volumes/Music Drive/Saltwater Almanac/03 Harbor Lights at Noon.m4a",
  .name: "Harbor Lights at Noon", .artist: "The Paper Lanterns", .album: "Saltwater Almanac",
  .albumArtist: "The Paper Lanterns", .composer: "Iris Fenwick", .genre: "Folk", .year: "2019",
  .trackNumber: "3", .trackCount: "11", .discNumber: "1", .discCount: "2", .compilation: "false",
  .bpm: "96", .grouping: "Side A", .work: "Tide Suite", .movement: "Ebb", .movementNumber: "2",
  .movementCount: "4", .rating: "80", .favorited: "true", .disliked: "false",
  .albumFavorited: "false", .albumDisliked: "true", .kind: "AAC audio file", .bitRate: "256",
  .sampleRate: "44100", .dateAdded: "2020/9/13/44800", .playedCount: "12", .skippedCount: "0",
  .playedDate: "2023/11/14/80000", .mediaKind: "song", .durationMs: "214000",
  .musicVersion: "1.5.0",
]

@Test func snapshotWithWrongFieldCountIsMalformed() {
  #expect(SnapshotParser.parse("A\u{1F}B") == .failure(.malformed("expected 36 fields, got 2")))
  #expect(SnapshotParser.parse("") == .failure(.musicNotRunning))
}

@Test func everyTextFieldParses() throws {
  let snap = try SnapshotParser.parse(snapshotLine(fullTrack)).get()
  #expect(snap.persistentID == "0A1B2C3D4E5F6071")
  #expect(snap.trackClass == "file track")
  #expect(snap.location == "/Volumes/Music Drive/Saltwater Almanac/03 Harbor Lights at Noon.m4a")
  #expect(snap.name == "Harbor Lights at Noon")
  #expect(snap.artist == "The Paper Lanterns")
  #expect(snap.album == "Saltwater Almanac")
  #expect(snap.albumArtist == "The Paper Lanterns")
  #expect(snap.composer == "Iris Fenwick")
  #expect(snap.genre == "Folk")
  #expect(snap.grouping == "Side A")
  #expect(snap.work == "Tide Suite")
  #expect(snap.movement == "Ebb")
  #expect(snap.kind == "AAC audio file")
  #expect(snap.mediaKind == "song")
  #expect(snap.musicVersion == "1.5.0")
}

@Test func everyNumericFieldParses() throws {
  let snap = try SnapshotParser.parse(snapshotLine(fullTrack), timeZone: utc).get()
  #expect(snap.year == 2019)
  #expect(snap.trackNumber == 3)
  #expect(snap.trackCount == 11)
  #expect(snap.discNumber == 1)
  #expect(snap.discCount == 2)
  #expect(snap.bpm == 96)
  #expect(snap.movementNumber == 2)
  #expect(snap.movementCount == 4)
  #expect(snap.rating == 80)
  #expect(snap.bitRate == 256)
  #expect(snap.sampleRate == 44100)
  #expect(snap.dateAdded == 1_600_000_000)
  #expect(snap.playedCount == 12)
  #expect(snap.skippedCount == 0)
  #expect(snap.playedDate == 1_700_000_000)
  #expect(snap.durationMs == 214000)
}

@Test func everyBooleanFieldParses() throws {
  let snap = try SnapshotParser.parse(snapshotLine(fullTrack)).get()
  #expect(snap.compilation == false)
  #expect(snap.favorited == true)
  #expect(snap.disliked == false)
  #expect(snap.albumFavorited == false)
  #expect(snap.albumDisliked == true)
}

@Test func emptyFieldsAreNil() throws {
  #expect(try SnapshotParser.parse(snapshotLine([:])).get() == TrackSnapshot())
}

@Test func missingValueIsNilForNumbersAndBooleansButTextForText() throws {
  let snap = try SnapshotParser.parse(
    snapshotLine([.bitRate: "missing value", .compilation: "missing value", .name: "missing value"])
  ).get()
  #expect(snap.bitRate == nil)
  #expect(snap.compilation == nil)
  #expect(snap.name == "missing value")
}

@Test func anythingButTrueOrFalseIsMalformed() {
  #expect(
    SnapshotParser.parse(snapshotLine([.favorited: "yes"]))
      == .failure(.malformed("favorited: expected true or false")))
  #expect(
    SnapshotParser.parse(snapshotLine([.compilation: "True"]))
      == .failure(.malformed("compilation: expected true or false")))
}

@Test func negativeCountIsMalformed() {
  #expect(
    SnapshotParser.parse(snapshotLine([.playedCount: "-1"]))
      == .failure(.malformed("playedCount: expected a non-negative integer")))
  #expect(
    SnapshotParser.parse(snapshotLine([.durationMs: "-5"]))
      == .failure(.malformed("durationMs: expected a non-negative integer")))
}

@Test func nonIntegerNumbersAreMalformed() {
  #expect(
    SnapshotParser.parse(snapshotLine([.year: "twenty"]))
      == .failure(.malformed("year: expected a non-negative integer")))
  #expect(
    SnapshotParser.parse(snapshotLine([.bpm: "96.5"]))
      == .failure(.malformed("bpm: expected a non-negative integer")))
}

@Test func datesBeforeTheEpochAreKept() throws {
  let snap = try SnapshotParser.parse(snapshotLine([.dateAdded: "1969/12/31/0"]), timeZone: utc)
    .get()
  #expect(snap.dateAdded == -86400)
}

@Test func datesAreLocalTimeInTheGivenZoneAcrossDaylightSaving() throws {
  let newYork = try #require(TimeZone(identifier: "America/New_York"))
  let line = snapshotLine([.dateAdded: "2024/1/15/43200", .playedDate: "2024/7/15/43200"])
  let snap = try SnapshotParser.parse(line, timeZone: newYork).get()
  // Noon in January is 17:00 UTC (EST), noon in July 16:00 UTC (EDT).
  #expect(snap.dateAdded == 1_705_338_000)
  #expect(snap.playedDate == 1_721_059_200)
}

@Test func repeatedFallBackHourTakesTheFirstMatch() throws {
  // 01:30 on 2024-11-03 happens twice in New York; Calendar picks the first, EDT, one.
  let newYork = try #require(TimeZone(identifier: "America/New_York"))
  let line = snapshotLine([.dateAdded: "2024/11/3/5400"])
  let snap = try SnapshotParser.parse(line, timeZone: newYork).get()
  #expect(snap.dateAdded == 1_730_611_800)
}

@Test func malformedDatePartsAreMalformed() {
  for parts in [
    "1600000000", "2024/1/15", "2024/1/15/0/0", "2024/13/1/0", "2024/0/1/0", "2024/2/30/0",
    "2024/1/0/0", "2024/1/15/86400", "2024/1/15/-1", "0/1/1/0", "a/b/c/d", "2024/1/15/1.5",
    "2024//15/0",
  ] {
    #expect(
      SnapshotParser.parse(snapshotLine([.playedDate: parts]), timeZone: utc)
        == .failure(.malformed("playedDate: expected Y/M/D/S")), "\(parts)")
  }
}

@Test func missingDateIsNil() throws {
  let snap = try SnapshotParser.parse(snapshotLine([.dateAdded: "missing value"])).get()
  #expect(snap.dateAdded == nil)
}

@Test func snapshotWithNoCurrentTrackSaysSo() {
  #expect(SnapshotParser.parse("stopped") == .failure(.noCurrentTrack))
  #expect(SnapshotParser.parse("playing") == .failure(.malformed("expected 36 fields, got 1")))
}

@Test func badPersistentIDIsMalformed() {
  #expect(
    SnapshotParser.parse(snapshotLine([.persistentID: "not hex"]))
      == .failure(.malformed("persistentID: expected 1 to 16 hex digits")))
}

@Test func tooManyFieldsIsMalformed() {
  let line = snapshotLine(fullTrack) + String(MusicScripts.separator)
  #expect(SnapshotParser.parse(line) == .failure(.malformed("expected 36 fields, got 37")))
}

@Test func aTextFieldOverTheCapIsDropped() throws {
  var track = fullTrack
  track[.name] = String(repeating: "a", count: 1 << 20)
  let snap = try SnapshotParser.parse(snapshotLine(track)).get()
  #expect(snap.name == nil)
  #expect(snap.artist == "The Paper Lanterns")
}

@Test func aTextFieldAtTheCapIsKept() throws {
  var track = fullTrack
  let atCap = String(repeating: "\u{E9}", count: FieldText.maxTextBytes / 2)
  track[.name] = atCap
  track[.album] = atCap + "a"
  let snap = try SnapshotParser.parse(snapshotLine(track)).get()
  #expect(snap.name == atCap)
  #expect(snap.album == nil)
}

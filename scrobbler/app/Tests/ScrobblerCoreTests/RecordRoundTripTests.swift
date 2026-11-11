import Foundation
import Testing

@testable import ScrobblerCore

/// The plain keys each valid sample carries beyond the defined ones; every other sample has
/// none. A defined key renamed or dropped lands in `otherInfo`, so this is what catches it.
private let expectedOtherInfo: [String: Set<String>] = ["single-audiobook.json": ["jukebox_room"]]

@Test func everyValidSampleRoundTripsLosslessly() throws {
  let names = try sampleNames(in: "valid")
  #expect(!names.isEmpty)
  for name in names {
    let original = try sampleData("valid", name)
    let record = try decodeByListenType(original)
    let others = Set(record.infos.flatMap(\.otherInfo.keys))
    #expect(others == expectedOtherInfo[name, default: []], "\(name)")
    #expect(
      try parsedDictionary(original).isEqual(try parsedDictionary(record.encoded())), "\(name)")
  }
}

/// The property names one schema object at `path` defines.
private func schemaProperties(_ file: String, _ path: [String]) throws -> Set<String> {
  let data = try Data(contentsOf: contractDir.appendingPathComponent("schemas/\(file)"))
  var node: Any = try JSONSerialization.jsonObject(with: data)
  for step in path {
    node = try #require((node as? [String: Any])?[step], "\(file): \(step)")
  }
  return Set(try #require(node as? [String: Any]).keys)
}

@Test func theDefinedKeysAreExactlyTheSchemasKeys() throws {
  var expected = try schemaProperties(
    "common.schema.json", ["$defs", "listenbrainz_info", "properties"])
  // The one documented key a client must never send: refused, not modeled.
  #expect(expected.remove("mbid_mapping") != nil)
  expected.formUnion(
    try schemaProperties("common.schema.json", ["$defs", "listensmith_track", "properties"]))
  expected.formUnion(
    try schemaProperties("listen.schema.json", ["$defs", "additional_info", "properties"]))
  expected.formUnion(
    try schemaProperties("now_playing.schema.json", ["$defs", "additional_info", "properties"]))
  #expect(AdditionalInfo.definedKeys == expected)
}

@Test func everyDefinedKeyIsCodedExactlyOnce() {
  let coded = AdditionalInfo.fields.map(\.key.stringValue).sorted()
  #expect(coded == AdditionalInfo.definedKeys.sorted())
}

@Test func aFractionalSecondsHeardIsRefused() {
  #expect(throws: DecodingError.self) {
    try RecordCoding.decode(ListenRecord.self, from: minimalListen(durationPlayed: "5.5"))
  }
}

@Test func theMinimalRecordsDecode() throws {
  let listen = try RecordCoding.decode(ListenRecord.self, from: minimalListen())
  #expect(listen.payload.first?.trackMetadata.additionalInfo.durationPlayed == 5)
  let now = try RecordCoding.decode(NowPlayingRecord.self, from: minimalNowPlaying())
  #expect(now.payload.first?.trackMetadata.additionalInfo.lsState == .playing)
}

@Test func anUndefinedPlainKeyIsKeptAndWrittenBack() throws {
  var info = AdditionalInfo()
  info.submissionClient = "c"
  info.otherInfo = ["jukebox_room": .string("den")]
  let metadata = TrackMetadata(artistName: "A", trackName: "T", additionalInfo: info)
  let data = try RecordCoding.encode(metadata)
  #expect(
    String(bytes: data, encoding: .utf8)
      == #"{"additional_info":{"jukebox_room":"den","submission_client":"c"},"#
      + #""artist_name":"A","track_name":"T"}"#)
  #expect(try RecordCoding.decode(TrackMetadata.self, from: data) == metadata)
}

@Test func additionalInfoRoundTripsOnItsOwn() throws {
  var info = AdditionalInfo()
  info.lsBpm = 120
  info.lsRate = 1.5
  info.otherInfo = ["jukebox_room": .array([.int(1), .null])]
  let data = try RecordCoding.encode(info)
  #expect(
    String(bytes: data, encoding: .utf8) == #"{"jukebox_room":[1,null],"ls_bpm":120,"ls_rate":1.5}"#
  )
  #expect(try RecordCoding.decode(AdditionalInfo.self, from: data) == info)
}

@Test func everyJSONValueKindSurvivesARoundTrip() throws {
  let text = #"{"a":null,"b":true,"c":3,"d":2.5,"e":"x/y","f":[1,"z"],"g":{"h":false}}"#
  let value = try RecordCoding.decode([String: JSONValue].self, from: Data(text.utf8))
  #expect(value["a"] == .null)
  #expect(value["b"] == .bool(true))
  #expect(value["c"] == .int(3))
  #expect(value["d"] == .double(2.5))
  #expect(value["e"] == .string("x/y"))
  #expect(value["f"] == .array([.int(1), .string("z")]))
  #expect(value["g"] == .object(["h": .bool(false)]))
  #expect(String(bytes: try RecordCoding.encode(value), encoding: .utf8) == text)
}

@Test func theOpenKeyTakesNoIntegerForm() {
  #expect(OpenCodingKey(intValue: 0) == nil)
  #expect(OpenCodingKey(stringValue: "k").intValue == nil)
}

@Test func theRecordsBuildFromTheirParts() {
  let metadata = TrackMetadata(
    artistName: "A", trackName: "T", releaseName: "R", additionalInfo: AdditionalInfo())
  let listen = ListenRecord(
    listenType: .single, payload: [Listen(listenedAt: 1_795_000_000, trackMetadata: metadata)])
  let now = NowPlayingRecord(
    listenType: .playingNow, payload: [NowPlayingItem(trackMetadata: metadata)])
  #expect(listen.payload.first?.trackMetadata.releaseName == "R")
  #expect(now.payload.first?.trackMetadata == metadata)
}

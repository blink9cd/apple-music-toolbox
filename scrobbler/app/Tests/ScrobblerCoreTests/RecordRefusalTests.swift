import Foundation
import Testing

@testable import ScrobblerCore

/// The invalid samples the record types accept, each with the schema rule that refuses it
/// instead. The types check structure (keys, value types, enums and which record a key
/// belongs to); bounds, patterns and the rules tying one key to another stay the schema's.
private let leftToTheSchema: [String: String] = [
  "both-durations.json": "duration and duration_ms are mutually exclusive",
  "both-played-durations.json": "duration_played and duration_played_ms are mutually exclusive",
  "bpm-zero.json": "ls_bpm's minimum",
  "catalog-without-id.json": "a catalog source requires ls_catalog_id",
  "listened-at-too-early.json": "listened_at's minimum",
  "local-file-without-path.json": "a local-file source requires ls_file_path",
  "missing-client-version.json": "additional_info's required keys",
  "missing-seconds-heard.json": "a listen requires duration_played or duration_played_ms",
  "piece-without-play-id.json": "ls_piece requires ls_play_id",
  "play-id-uppercase.json": "ls_play_id's pattern",
  "playing-now-without-position.json": "a now-playing item's required keys",
  "playing-now-zero-rate.json": "ls_rate's exclusive minimum",
  "single-with-two-listens.json": "a single submission's one-item payload",
]

@Test func everyInvalidSampleTheStructureCanSeeIsRefused() throws {
  let names = try sampleNames(in: "invalid")
  #expect(Set(leftToTheSchema.keys).isSubset(of: Set(names)))
  for name in names {
    let refused = refusedByEveryRecordType(try sampleData("invalid", name))
    // A sample that starts being refused moves out of leftToTheSchema, so the list stays true.
    #expect(refused == (leftToTheSchema[name] == nil), "\(name)")
  }
}

@Test func aRecordOfTheOtherTypeIsRefused() throws {
  let listen = try sampleData("valid", "single-local-file.json")
  #expect(throws: DecodingError.self) {
    try RecordCoding.decode(NowPlayingRecord.self, from: listen)
  }
  let now = try sampleData("valid", "playing-now-local-file.json")
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: now) }
}

/// `data` with its listen_type swapped for `listenType`, the rest of it untouched.
private func relabeled(_ data: Data, as listenType: String) throws -> Data {
  var object = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
  object["listen_type"] = listenType
  return try JSONSerialization.data(withJSONObject: object)
}

@Test(arguments: ["playing_now"])
func aListenUnderAnotherListenTypeIsRefused(listenType: String) throws {
  let data = try relabeled(minimalListen(), as: listenType)
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: data) }
}

@Test(arguments: ["single", "import"])
func aNowPlayingItemUnderAnotherListenTypeIsRefused(listenType: String) throws {
  let data = try relabeled(minimalNowPlaying(), as: listenType)
  #expect(throws: DecodingError.self) { try RecordCoding.decode(NowPlayingRecord.self, from: data) }
}

@Test(arguments: [
  #","ls_state":"paused""#, #","ls_rate":1.5"#, #","ls_position_seconds":3"#,
  #","ls_measured_at":1795000000"#,
])
func aListenCarryingANowPlayingKeyIsRefused(key: String) {
  #expect(throws: DecodingError.self) {
    try RecordCoding.decode(ListenRecord.self, from: minimalListen(info: key))
  }
}

@Test func aNowPlayingItemCarryingAPieceIsRefused() {
  #expect(throws: DecodingError.self) {
    try RecordCoding.decode(NowPlayingRecord.self, from: minimalNowPlaying(info: #","ls_piece":1"#))
  }
}

@Test(arguments: [
  ["info": #","isrc":null"#], ["metadata": #","release_name":null"#],
])
func aNullOnADefinedKeyIsRefused(splice: [String: String]) {
  let data = minimalListen(
    metadata: splice["metadata", default: ""], info: splice["info", default: ""])
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: data) }
}

@Test func aNullOnAPlainKeyIsKept() throws {
  let record = try RecordCoding.decode(
    ListenRecord.self, from: minimalListen(info: #","room":null"#))
  #expect(record.payload.first?.trackMetadata.additionalInfo.otherInfo == ["room": .null])
}

@Test(arguments: ["submission", "listen", "metadata"])
func anUnknownKeyOutsideAdditionalInfoIsRefused(level: String) {
  let stray = #","stray":1"#
  let data = minimalListen(
    submission: level == "submission" ? stray : "", listen: level == "listen" ? stray : "",
    metadata: level == "metadata" ? stray : "")
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: data) }
}

@Test func anUnknownKeyInANowPlayingItemIsRefused() throws {
  let data = try sampleData("invalid", "playing-now-with-listened-at.json")
  #expect(throws: DecodingError.self) { try RecordCoding.decode(NowPlayingRecord.self, from: data) }
}

@Test func anUnknownListensmithKeyIsRefused() throws {
  let data = try sampleData("invalid", "unknown-ls-key.json")
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: data) }
}

@Test func aSentMbidMappingIsRefused() throws {
  let data = try sampleData("invalid", "mbid-mapping-sent.json")
  #expect(throws: DecodingError.self) { try RecordCoding.decode(ListenRecord.self, from: data) }
}

@Test(arguments: ["ls_bpm", "duration", "ls_invented", "mbid_mapping"])
func otherInfoCannotCarryADefinedOrForbiddenKey(key: String) {
  var info = AdditionalInfo()
  info.otherInfo = [key: .int(1)]
  #expect(throws: EncodingError.self) { try RecordCoding.encode(info) }
}

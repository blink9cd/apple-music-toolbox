import Foundation
import Testing

@testable import ScrobblerCore

/// The scrobbler folder, four levels above this file: Tests/ScrobblerCoreTests/ -> app/ ->.
let scrobblerDir = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
  .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
/// The checked copy of the contract.
let contractDir = scrobblerDir.appendingPathComponent("contract")
/// Sample files whose names start with this are play-count baselines, not listens.
let baselinePrefix = "baseline-"

/// The shared defaults file in the scrobbler's copy of the contract, which the tests pin
/// the app's ports and queue cap against.
func contractDefaults() throws -> [String: Any] {
  let url = contractDir.appendingPathComponent("defaults.json")
  return try #require(
    try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
}

/// Every listen sample in one of the copy's sample folders, by file name.
func sampleNames(in folder: String) throws -> [String] {
  let names = try FileManager.default.contentsOfDirectory(
    atPath: contractDir.appendingPathComponent("samples/\(folder)").path)
  return names.filter { $0.hasSuffix(".json") && !$0.hasPrefix(baselinePrefix) }.sorted()
}

/// One sample file's bytes.
func sampleData(_ folder: String, _ name: String) throws -> Data {
  try Data(contentsOf: contractDir.appendingPathComponent("samples/\(folder)/\(name)"))
}

/// A record decoded with the type its own listen_type names.
enum DecodedRecord {
  case listen(ListenRecord)
  case nowPlaying(NowPlayingRecord)

  /// Every item's `additional_info`.
  var infos: [AdditionalInfo] {
    switch self {
    case .listen(let record): record.payload.map(\.trackMetadata.additionalInfo)
    case .nowPlaying(let record): record.payload.map(\.trackMetadata.additionalInfo)
    }
  }

  /// The record encoded again.
  func encoded() throws -> Data {
    switch self {
    case .listen(let record): try RecordCoding.encode(record)
    case .nowPlaying(let record): try RecordCoding.encode(record)
    }
  }
}

/// Decode a submission with the type its listen_type names.
func decodeByListenType(_ data: Data) throws -> DecodedRecord {
  let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
  let raw = try #require(object?["listen_type"] as? String)
  switch try #require(ListenType(rawValue: raw)) {
  case .playingNow: return .nowPlaying(try RecordCoding.decode(NowPlayingRecord.self, from: data))
  case .single, .import: return .listen(try RecordCoding.decode(ListenRecord.self, from: data))
  }
}

/// Whether neither record type will decode `data`.
func refusedByEveryRecordType(_ data: Data) -> Bool {
  (try? RecordCoding.decode(ListenRecord.self, from: data)) == nil
    && (try? RecordCoding.decode(NowPlayingRecord.self, from: data)) == nil
}

/// A JSON text parsed as a dictionary, for an `isEqual` comparison that ignores key order.
func parsedDictionary(_ data: Data) throws -> NSDictionary {
  try #require(try JSONSerialization.jsonObject(with: data) as? NSDictionary)
}

/// A minimal valid single listen. Each argument is spliced into its level as written, so a
/// test adds a key (`,"stray":1`) or replaces the seconds heard.
func minimalListen(
  submission: String = "", listen: String = "", metadata: String = "",
  info: String = "", durationPlayed: String = "5"
) -> Data {
  let text = """
    {"listen_type":"single"\(submission),"payload":[{"listened_at":1795000000\(listen),\
    "track_metadata":{"artist_name":"A","track_name":"T"\(metadata),\
    "additional_info":{"submission_client":"c","submission_client_version":"1",\
    "duration_played":\(durationPlayed)\(info)}}}]}
    """
  return Data(text.utf8)
}

/// A minimal valid now-playing item, with `info` spliced into its `additional_info`.
func minimalNowPlaying(info: String = "") -> Data {
  let text = """
    {"listen_type":"playing_now","payload":[{"track_metadata":{"artist_name":"A",\
    "track_name":"T","additional_info":{"submission_client":"c",\
    "submission_client_version":"1","ls_position_seconds":1,"ls_state":"playing",\
    "ls_measured_at":1795000000\(info)}}}]}
    """
  return Data(text.utf8)
}

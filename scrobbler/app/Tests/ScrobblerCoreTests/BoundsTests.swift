import Foundation
import Testing

@testable import ScrobblerCore

/// One schema property: its key and its JSON Schema object, any `$ref` already followed.
private typealias SchemaProperty = (key: String, schema: [String: Any])

/// The copied schemas folder.
private let schemasDir = contractDir.appendingPathComponent("schemas")

/// One copied schema file as a JSON object.
private func loadSchema(_ name: String) throws -> [String: Any] {
  let data = try Data(contentsOf: schemasDir.appendingPathComponent(name))
  return try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
}

/// The object at `path` below `object`.
private func object(_ object: [String: Any], at path: [String]) throws -> [String: Any] {
  var current = object
  for key in path {
    current = try #require(current[key] as? [String: Any], "missing \(key)")
  }
  return current
}

/// `schema` with a `$ref` into the common schema's definitions replaced by its target.
private func resolved(_ schema: [String: Any], common: [String: Any]) throws -> [String: Any] {
  guard let ref = schema["$ref"] as? String else { return schema }
  let name = try #require(ref.components(separatedBy: "#/$defs/").last)
  return try object(common, at: ["$defs", name])
}

/// Every property a built record may carry, with its schema: both records' additional_info
/// keys, and a listen's listened_at.
private func recordProperties() throws -> [SchemaProperty] {
  let common = try loadSchema("common.schema.json")
  let listen = try loadSchema("listen.schema.json")
  let nowPlaying = try loadSchema("now_playing.schema.json")
  let sources = [
    try object(common, at: ["$defs", "listenbrainz_info", "properties"]),
    try object(common, at: ["$defs", "listensmith_track", "properties"]),
    try object(listen, at: ["$defs", "additional_info", "properties"]),
    try object(nowPlaying, at: ["$defs", "additional_info", "properties"]),
    try object(listen, at: ["$defs", "listen", "properties"]),
  ]
  var properties: [SchemaProperty] = []
  for source in sources {
    for (key, value) in source {
      let schema = try #require(value as? [String: Any])
      properties.append((key, try resolved(schema, common: common)))
    }
  }
  return properties
}

/// The properties of JSON Schema type `type`.
private func properties(ofType type: String) throws -> [SchemaProperty] {
  try recordProperties().filter { $0.schema["type"] as? String == type }
}

@Test func everyBoundedIntegerKeyHasTheSchemaRangeInSwift() throws {
  var schemaBounds: [String: ClosedRange<Int>] = [:]
  for (key, schema) in try properties(ofType: "integer") {
    // An integer the schema leaves unbounded must stay unbounded in Swift too, so it is
    // left out here and the equality below refuses a Swift range for it.
    guard let low = schema["minimum"] as? Int, let high = schema["maximum"] as? Int else {
      continue
    }
    schemaBounds[key] = low...high
  }
  #expect(!schemaBounds.isEmpty)
  #expect(RecordBuilder.bounds == schemaBounds)
}

@Test func everyNumberKeyTheBuilderWritesHasTheSchemaRangeInSwift() throws {
  var schemaBounds: [String: ClosedRange<Double>] = [:]
  var exclusive: [String] = []
  for (key, schema) in try properties(ofType: "number") {
    if schema["exclusiveMinimum"] != nil || schema["exclusiveMaximum"] != nil {
      exclusive.append(key)
      continue
    }
    guard let low = schema["minimum"] as? Double, let high = schema["maximum"] as? Double else {
      continue
    }
    schemaBounds[key] = low...high
  }
  #expect(RecordBuilder.numberBounds == schemaBounds)
  // The playback rate has an exclusive bound, and the builder never writes it: the
  // scrobbler does not read the player's rate, and an absent rate reads as 1.
  #expect(exclusive == ["ls_rate"])
}

import Foundation

/// The one JSON form every record takes, on disk in the queue and on the wire alike.
public enum RecordCoding {
  /// Compact, sorted keys, slashes unescaped: the queue's and the golden folder's bytes.
  ///
  /// Sorted keys make the bytes a function of the record alone, so a golden file can be
  /// compared byte for byte; unescaped slashes keep a file path readable in the queue.
  public static func encode<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    return try encoder.encode(value)
  }

  /// Decode one record of `type` from its JSON bytes.
  public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
    try JSONDecoder().decode(type, from: data)
  }
}

/// Any JSON value, for the `additional_info` keys the contract allows but does not define.
///
/// Integers and fractions stay apart, so a whole number read back is written back whole.
public indirect enum JSONValue: Codable, Equatable, Sendable {
  /// `null`.
  case null
  /// `true` or `false`.
  case bool(Bool)
  /// A number with no fraction that fits in an `Int`.
  case int(Int)
  /// Any other number.
  case double(Double)
  /// A string.
  case string(String)
  /// An array.
  case array([JSONValue])
  /// An object.
  case object([String: JSONValue])

  /// Decode whichever kind of value the JSON holds. Booleans are tried before numbers and
  /// integers before fractions, so each value lands in its narrowest case.
  public init(from decoder: any Decoder) throws {
    let container = try decoder.singleValueContainer()
    if container.decodeNil() {
      self = .null
    } else if let value = try? container.decode(Bool.self) {
      self = .bool(value)
    } else if let value = try? container.decode(Int.self) {
      self = .int(value)
    } else if let value = try? container.decode(Double.self) {
      self = .double(value)
    } else if let value = try? container.decode(String.self) {
      self = .string(value)
    } else if let value = try? container.decode([JSONValue].self) {
      self = .array(value)
    } else {
      self = .object(try container.decode([String: JSONValue].self))
    }
  }

  /// Encode the value as the kind it holds.
  public func encode(to encoder: any Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .null: try container.encodeNil()
    case .bool(let value): try container.encode(value)
    case .int(let value): try container.encode(value)
    case .double(let value): try container.encode(value)
    case .string(let value): try container.encode(value)
    case .array(let value): try container.encode(value)
    case .object(let value): try container.encode(value)
    }
  }
}

/// A coding key for any string, to read every key an object holds.
struct OpenCodingKey: CodingKey {
  let stringValue: String
  /// Always nil: every record key is a string.
  var intValue: Int? { nil }

  init(stringValue: String) {
    self.stringValue = stringValue
  }

  /// No key here is an integer, so an integer key is refused.
  init?(intValue: Int) {
    nil
  }

  /// Every key the object `decoder` holds.
  static func keys(of decoder: any Decoder) throws -> [String] {
    try decoder.container(keyedBy: OpenCodingKey.self).allKeys.map(\.stringValue)
  }

  /// Throw when the object `decoder` holds a key `Keys` does not name, so an undefined key is
  /// refused rather than dropped without a word.
  static func refuseKeys<Keys: CodingKey & CaseIterable>(
    of decoder: any Decoder, outside _: Keys.Type
  ) throws {
    let known = Set(Keys.allCases.map(\.stringValue))
    let unknown = try keys(of: decoder).filter { !known.contains($0) }.sorted()
    if !unknown.isEmpty {
      throw refusal("undefined keys: \(unknown.joined(separator: ", "))", at: decoder.codingPath)
    }
  }

  /// Throw when the object `decoder` holds a null under one of `keys`. The contract gives no
  /// defined key a null, and an optional property would otherwise read it as absent.
  static func refuseNulls(of decoder: any Decoder, among keys: Set<String>) throws {
    let container = try decoder.container(keyedBy: OpenCodingKey.self)
    let nulls = try container.allKeys.filter {
      try keys.contains($0.stringValue) && container.decodeNil(forKey: $0)
    }
    if let first = nulls.map(\.stringValue).sorted().first {
      throw refusal("null on \(first)", at: decoder.codingPath)
    }
  }

  /// The error a record that breaks the contract's shape is refused with.
  static func refusal(_ message: String, at codingPath: [any CodingKey]) -> DecodingError {
    DecodingError.dataCorrupted(.init(codingPath: codingPath, debugDescription: message))
  }
}

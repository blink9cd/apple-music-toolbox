import Foundation

/// Why the config file was refused. Each case names a key, or the whole file, and never
/// quotes the file's content.
public enum ConfigError: Error, Equatable, Sendable {
  /// The file exists but could not be read: not a regular file, unopenable, or too large.
  case unreadable
  /// The file is not one JSON object.
  case notAnObject
  /// A key the config does not define; an unnamed one when the key is not a plain name.
  case unknownKey(String)
  /// A defined key holding a value outside its rule.
  case invalidValue(key: String)

  /// What an error about the file as a whole names, rather than one key.
  public static let wholeFile = "(file)"
  /// What an unknown key that is not a plain name is reported as, so arbitrary text from
  /// the file never reaches a log or `status.json`.
  public static let unnamedKey = "(unnamed key)"

  /// The key the error is about, or `wholeFile`.
  public var key: String {
    switch self {
    case .unreadable, .notAnObject: Self.wholeFile
    case .unknownKey(let key), .invalidValue(let key): key
    }
  }
}

/// The scrobbler's settings, from its config file outside every checkout.
public struct ScrobblerConfig: Equatable, Sendable {
  /// The store's port; `contract/defaults.json`'s `store_port`, which a test pins.
  public static let defaultStorePort = 47831
  /// The relay's port, which the store may never share; `contract/defaults.json`'s
  /// `relay_port`, which a test pins.
  public static let defaultRelayPort = 47832
  /// The ports the store and the relay may listen on: above the privileged range.
  public static let allowedPorts = 1024...65535
  /// The largest config file read; a real one is a few dozen bytes.
  public static let maxFileBytes = 65536
  /// The address the store and the relay bind, and the only one a record is sent to.
  static let loopbackHost = "127.0.0.1"
  /// The submit endpoint, the same path on the store and the relay.
  static let submitPath = "/1/submit-listens"
  /// The store's port key.
  static let storePortKey = "store_port"
  /// The relay's port key.
  static let relayPortKey = "relay_port"
  /// Every key the file may hold.
  static let knownKeys: Set<String> = [storePortKey, relayPortKey]
  /// The longest unknown key that is named back.
  private static let maxNamedKeyLength = 64

  /// The port the store listens on, on the loopback address.
  public var storePort: Int
  /// The port the relay listens on, on the loopback address.
  public var relayPort: Int

  /// The settings with `storePort` and `relayPort`.
  public init(storePort: Int = defaultStorePort, relayPort: Int = defaultRelayPort) {
    self.storePort = storePort
    self.relayPort = relayPort
  }

  /// Where listens are posted: the store's submit endpoint on the loopback address only,
  /// so the token is sent nowhere else. A port outside `allowedPorts`, which `load` never
  /// gives, is replaced by the default rather than forming a bad URL.
  public var submitURL: URL {
    Self.loopbackSubmitURL(port: storePort, fallback: Self.defaultStorePort)
  }

  /// Where what is playing now is posted: the relay's submit endpoint on the loopback
  /// address only, with the same fallback as `submitURL`.
  public var relayURL: URL {
    Self.loopbackSubmitURL(port: relayPort, fallback: Self.defaultRelayPort)
  }

  /// The submit endpoint at `port` on the loopback address, or at `fallback` when `port`
  /// is outside `allowedPorts`.
  private static func loopbackSubmitURL(port: Int, fallback: Int) -> URL {
    let port = allowedPorts.contains(port) ? port : fallback
    // A fixed scheme, host and path with a port of at most five digits always parse.
    return URL(string: "http://\(loopbackHost):\(port)\(submitPath)")!
  }

  /// The settings in the file at `url`: the defaults when no file is there.
  public static func load(from url: URL) throws(ConfigError) -> ScrobblerConfig {
    // Non-blocking, so a FIFO planted at the path cannot hang the app at start.
    let descriptor = open(url.path, O_RDONLY | O_NONBLOCK | O_CLOEXEC)
    guard descriptor >= 0 else {
      if errno == ENOENT { return ScrobblerConfig() }
      throw .unreadable
    }
    defer { close(descriptor) }
    guard FileIO.isRegularFile(FileIO.status(of: descriptor)) else { throw .unreadable }
    let data = FileIO.readBytes(descriptor, upTo: maxFileBytes + 1)
    guard data.count <= maxFileBytes else { throw .unreadable }
    return try parse(data)
  }

  /// The settings `data` holds, refusing an undefined key, a bad value, and the two ports
  /// being one. When they are, the relay's key is named if the file set it, else the
  /// store's, so the error names a key the file holds.
  static func parse(_ data: Data) throws(ConfigError) -> ScrobblerConfig {
    guard let object = try? RecordCoding.decode([String: JSONValue].self, from: data) else {
      throw .notAnObject
    }
    if let unknown = object.keys.filter({ !knownKeys.contains($0) }).sorted().first {
      throw .unknownKey(reportableKey(unknown))
    }
    let config = ScrobblerConfig(
      storePort: try port(in: object, at: storePortKey) ?? defaultStorePort,
      relayPort: try port(in: object, at: relayPortKey) ?? defaultRelayPort)
    guard config.storePort != config.relayPort else {
      throw .invalidValue(key: object[relayPortKey] != nil ? relayPortKey : storePortKey)
    }
    return config
  }

  /// The port `object` holds at `key`, nil when the key is absent; anything but a whole
  /// number in `allowedPorts` is refused, naming `key`.
  private static func port(in object: [String: JSONValue], at key: String) throws(ConfigError)
    -> Int?
  {
    guard let value = object[key] else { return nil }
    guard case .int(let port) = value, allowedPorts.contains(port) else {
      throw .invalidValue(key: key)
    }
    return port
  }

  /// `key` when it is a plain name of letters, digits and underscores; `unnamedKey` else.
  static func reportableKey(_ key: String) -> String {
    let plain = key.utf8.allSatisfy { byte in
      byte == UInt8(ascii: "_") || (byte < 0x80 && Character(Unicode.Scalar(byte)).isLetter)
        || (UInt8(ascii: "0")...UInt8(ascii: "9")).contains(byte)
    }
    return plain && (1...maxNamedKeyLength).contains(key.count) ? key : ConfigError.unnamedKey
  }
}

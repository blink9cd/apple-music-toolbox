import Foundation

/// The kind of submission, the `listen_type` key.
public enum ListenType: String, Codable, Sendable {
  /// One finished listen.
  case single
  /// A batch of finished listens, sent together.
  case `import`
  /// What is playing now; never stored as a listen.
  case playingNow = "playing_now"
}

/// An item a submission carries, naming the listen types it may be sent under.
public protocol SubmissionItem: Codable, Equatable, Sendable {
  /// The listen types a submission of this item may name.
  static var listenTypes: Set<ListenType> { get }
}

/// One submission: its kind and its items, a listen or a now-playing item each.
///
/// Decoding refuses what the contract's structure refuses, at this level and every level
/// below: an undefined key, a null on a defined key, a listen type the item does not take,
/// and a key that belongs to the other kind of record. So a record the scrobbler reads back
/// is the record it wrote. Bounds and patterns are left to the schema.
public struct Submission<Item: SubmissionItem>: Codable, Equatable, Sendable {
  /// The kind of submission.
  public var listenType: ListenType
  /// The listens, or the one now-playing item.
  public var payload: [Item]

  enum CodingKeys: String, CodingKey, CaseIterable {
    case listenType = "listen_type"
    case payload
  }

  /// A submission of `payload`'s items as `listenType`.
  public init(listenType: ListenType, payload: [Item]) {
    self.listenType = listenType
    self.payload = payload
  }

  /// Decode a submission, refusing an undefined key and a listen type `Item` does not take.
  public init(from decoder: any Decoder) throws {
    try OpenCodingKey.refuseKeys(of: decoder, outside: CodingKeys.self)
    let container = try decoder.container(keyedBy: CodingKeys.self)
    listenType = try container.decode(ListenType.self, forKey: .listenType)
    guard Item.listenTypes.contains(listenType) else {
      throw OpenCodingKey.refusal(
        "listen_type \(listenType.rawValue) does not take this record", at: decoder.codingPath)
    }
    payload = try container.decode([Item].self, forKey: .payload)
  }
}

/// One finished listen.
public struct Listen: SubmissionItem {
  /// A listen is sent alone or in a batch.
  public static let listenTypes: Set<ListenType> = [.single, .import]
  /// When the listen started, in Unix seconds.
  public var listenedAt: Int
  /// What was heard.
  public var trackMetadata: TrackMetadata

  enum CodingKeys: String, CodingKey, CaseIterable {
    case listenedAt = "listened_at"
    case trackMetadata = "track_metadata"
  }

  /// A listen of `trackMetadata` that started at `listenedAt`.
  public init(listenedAt: Int, trackMetadata: TrackMetadata) {
    self.listenedAt = listenedAt
    self.trackMetadata = trackMetadata
  }

  /// Decode a listen, refusing an undefined key and a now-playing key.
  public init(from decoder: any Decoder) throws {
    try OpenCodingKey.refuseKeys(of: decoder, outside: CodingKeys.self)
    let container = try decoder.container(keyedBy: CodingKeys.self)
    listenedAt = try container.decode(Int.self, forKey: .listenedAt)
    trackMetadata = try container.decode(TrackMetadata.self, forKey: .trackMetadata)
    try trackMetadata.additionalInfo.refuseKeys(
      AdditionalInfo.nowPlayingOnlyKeys, at: decoder.codingPath)
  }
}

/// What is playing now; it carries no `listened_at`.
public struct NowPlayingItem: SubmissionItem {
  /// A now-playing item is sent only as `playing_now`.
  public static let listenTypes: Set<ListenType> = [.playingNow]
  /// What is playing.
  public var trackMetadata: TrackMetadata

  enum CodingKeys: String, CodingKey, CaseIterable {
    case trackMetadata = "track_metadata"
  }

  /// The item playing `trackMetadata`.
  public init(trackMetadata: TrackMetadata) {
    self.trackMetadata = trackMetadata
  }

  /// Decode a now-playing item, refusing an undefined key and a listen-only key.
  public init(from decoder: any Decoder) throws {
    try OpenCodingKey.refuseKeys(of: decoder, outside: CodingKeys.self)
    let container = try decoder.container(keyedBy: CodingKeys.self)
    trackMetadata = try container.decode(TrackMetadata.self, forKey: .trackMetadata)
    try trackMetadata.additionalInfo.refuseKeys(
      AdditionalInfo.listenOnlyKeys, at: decoder.codingPath)
  }
}

/// The track a listen or a now-playing item is of.
public struct TrackMetadata: Codable, Equatable, Sendable {
  /// The track artist.
  public var artistName: String
  /// The track title.
  public var trackName: String
  /// The album, when the track has one.
  public var releaseName: String?
  /// Everything else known about the track and the play.
  public var additionalInfo: AdditionalInfo

  enum CodingKeys: String, CodingKey, CaseIterable {
    case artistName = "artist_name"
    case trackName = "track_name"
    case releaseName = "release_name"
    case additionalInfo = "additional_info"
  }

  /// The track `trackName` by `artistName`, on `releaseName` when given.
  public init(
    artistName: String, trackName: String, releaseName: String? = nil,
    additionalInfo: AdditionalInfo
  ) {
    self.artistName = artistName
    self.trackName = trackName
    self.releaseName = releaseName
    self.additionalInfo = additionalInfo
  }

  /// Decode the track, refusing an undefined key and a null album.
  public init(from decoder: any Decoder) throws {
    try OpenCodingKey.refuseKeys(of: decoder, outside: CodingKeys.self)
    try OpenCodingKey.refuseNulls(of: decoder, among: [CodingKeys.releaseName.stringValue])
    let container = try decoder.container(keyedBy: CodingKeys.self)
    artistName = try container.decode(String.self, forKey: .artistName)
    trackName = try container.decode(String.self, forKey: .trackName)
    releaseName = try container.decodeIfPresent(String.self, forKey: .releaseName)
    additionalInfo = try container.decode(AdditionalInfo.self, forKey: .additionalInfo)
  }
}

/// A finished-listen submission, `single` or `import`.
public typealias ListenRecord = Submission<Listen>
/// A `playing_now` submission.
public typealias NowPlayingRecord = Submission<NowPlayingItem>

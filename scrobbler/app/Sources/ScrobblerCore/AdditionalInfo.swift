import Foundation

/// Where the audio came from, the `ls_source` key; not the submitting client.
public enum LsSource: String, Codable, Sendable {
  /// A file on this machine; the record then carries `ls_file_path`.
  case localFile = "local_file"
  /// A streaming catalog; the record then carries `ls_catalog_id`.
  case catalog
  /// A radio stream.
  case radio
}

/// The kind of audio, the `ls_media_type` key; a record without it reads as music.
public enum LsMediaType: String, Codable, Sendable {
  /// Music.
  case music
  /// A podcast episode.
  case podcast
  /// An audiobook part.
  case audiobook
  /// Anything else.
  case other
}

/// The player's state, the `ls_state` key of a now-playing item.
public enum LsState: String, Codable, Sendable {
  /// Playing.
  case playing
  /// Paused.
  case paused
  /// Waiting for audio.
  case buffering
  /// Stopped.
  case stopped
}

/// A record's `additional_info`: one optional property per key the contract defines for a
/// listen or a now-playing item, plus `otherInfo` for the plain keys it allows but does not
/// define.
///
/// Every property maps to the JSON key its `CodingKeys` case names. A key the scrobbler never
/// writes is modeled all the same, so any valid record reads back losslessly. A key the
/// contract refuses (an undefined `ls_` key, or `mbid_mapping`), and a null on a defined key,
/// are refused when the info is decoded; `otherInfo` keeps only the plain keys left over.
public struct AdditionalInfo: Codable, Equatable, Sendable {
  // ListenBrainz's documented keys.
  /// The track artists' MusicBrainz IDs.
  public var artistMbids: [String]?
  /// The release group's MusicBrainz ID.
  public var releaseGroupMbid: String?
  /// The release's MusicBrainz ID.
  public var releaseMbid: String?
  /// The recording's MusicBrainz ID.
  public var recordingMbid: String?
  /// The track's MusicBrainz ID.
  public var trackMbid: String?
  /// The works' MusicBrainz IDs.
  public var workMbids: [String]?
  /// The track number, as text.
  public var tracknumber: String?
  /// The recording's ISRC.
  public var isrc: String?
  /// The track's Spotify ID.
  public var spotifyID: String?
  /// Free tags.
  public var tags: [String]?
  /// The player that played the track.
  public var mediaPlayer: String?
  /// The player's version.
  public var mediaPlayerVersion: String?
  /// The client that submitted the record.
  public var submissionClient: String?
  /// The submitting client's version.
  public var submissionClientVersion: String?
  /// The client that first submitted the record, when another relays it.
  public var originalSubmissionClient: String?
  /// The streaming service's domain.
  public var musicService: String?
  /// The streaming service's name.
  public var musicServiceName: String?
  /// Where the track can be found online.
  public var originURL: String?
  /// The record label.
  public var label: String?
  /// The track's length in milliseconds; never sent beside `duration`.
  public var durationMs: Int?
  /// The track's length in seconds; never sent beside `duration_ms`.
  public var duration: Int?
  /// Seconds heard; never sent beside `duration_played_ms`.
  public var durationPlayed: Int?
  /// Milliseconds heard; never sent beside `duration_played`.
  public var durationPlayedMs: Int?

  // listensmith's identity, source and media-type keys.
  /// Where the audio came from.
  public var lsSource: LsSource?
  /// The kind of audio.
  public var lsMediaType: LsMediaType?
  /// The audio file's path on the machine that played it.
  public var lsFilePath: String?
  /// The player's own persistent ID for the track.
  public var lsPersistentID: String?
  /// The streaming catalog's ID for the track.
  public var lsCatalogID: String?
  /// The ID of one play, lowercase, shared by every piece of it.
  public var lsPlayID: String?
  /// The album artist, when it differs from the track artist.
  public var lsAlbumArtist: String?
  /// The disc number within a multi-disc release.
  public var lsDiscNumber: Int?
  /// The genre tag.
  public var lsGenre: String?
  /// The release year tag.
  public var lsYear: Int?

  // The Music.app fields read when a play starts.
  /// The composer tag.
  public var lsComposer: String?
  /// How many tracks the disc holds.
  public var lsTrackCount: Int?
  /// How many discs the release holds.
  public var lsDiscCount: Int?
  /// Whether the track is part of a compilation.
  public var lsCompilation: Bool?
  /// The beats-per-minute tag; absent rather than 0 when none.
  public var lsBpm: Int?
  /// The grouping tag.
  public var lsGrouping: String?
  /// The classical work the track belongs to.
  public var lsWork: String?
  /// The movement's name within its work.
  public var lsMovement: String?
  /// The movement's number within its work.
  public var lsMovementNumber: Int?
  /// How many movements the work has.
  public var lsMovementCount: Int?
  /// Music.app's rating, 20 per star.
  public var lsMusicRating: Int?
  /// Whether Music.app holds the track as a favorite.
  public var lsMusicFavorited: Bool?
  /// Whether Music.app holds the track as disliked.
  public var lsMusicDisliked: Bool?
  /// Whether Music.app holds the album as a favorite.
  public var lsMusicAlbumFavorited: Bool?
  /// Whether Music.app holds the album as disliked.
  public var lsMusicAlbumDisliked: Bool?
  /// Music.app's kind string for the file.
  public var lsKind: String?
  /// The file's bit rate in kilobits per second.
  public var lsBitRate: Int?
  /// The file's sample rate in hertz.
  public var lsSampleRate: Int?
  /// When the track entered Music.app's library, in Unix seconds.
  public var lsMusicDateAdded: Int?
  /// Music.app's play count before this play.
  public var lsMusicPlayedCount: Int?
  /// Music.app's skip count before this play.
  public var lsMusicSkippedCount: Int?
  /// Music.app's last-played time before this play, in Unix seconds.
  public var lsMusicPlayedDate: Int?

  // A listen's piece of a play split by a long pause.
  /// Which piece this record is, counting from 1; needs `ls_play_id`.
  public var lsPiece: Int?

  // A now-playing item's player state.
  /// Seconds into the track when `ls_measured_at` was read.
  public var lsPositionSeconds: Double?
  /// The player's state.
  public var lsState: LsState?
  /// The playback speed; 1 when absent.
  public var lsRate: Double?
  /// The Unix time, in seconds, at which `ls_position_seconds` was read.
  public var lsMeasuredAt: Double?

  /// The plain keys the contract allows but does not define, kept so they are written back.
  public var otherInfo: [String: JSONValue] = [:]

  enum CodingKeys: String, CodingKey, CaseIterable {
    case artistMbids = "artist_mbids"
    case releaseGroupMbid = "release_group_mbid"
    case releaseMbid = "release_mbid"
    case recordingMbid = "recording_mbid"
    case trackMbid = "track_mbid"
    case workMbids = "work_mbids"
    case tracknumber
    case isrc
    case spotifyID = "spotify_id"
    case tags
    case mediaPlayer = "media_player"
    case mediaPlayerVersion = "media_player_version"
    case submissionClient = "submission_client"
    case submissionClientVersion = "submission_client_version"
    case originalSubmissionClient = "original_submission_client"
    case musicService = "music_service"
    case musicServiceName = "music_service_name"
    case originURL = "origin_url"
    case label
    case durationMs = "duration_ms"
    case duration
    case durationPlayed = "duration_played"
    case durationPlayedMs = "duration_played_ms"
    case lsSource = "ls_source"
    case lsMediaType = "ls_media_type"
    case lsFilePath = "ls_file_path"
    case lsPersistentID = "ls_persistent_id"
    case lsCatalogID = "ls_catalog_id"
    case lsPlayID = "ls_play_id"
    case lsAlbumArtist = "ls_album_artist"
    case lsDiscNumber = "ls_disc_number"
    case lsGenre = "ls_genre"
    case lsYear = "ls_year"
    case lsComposer = "ls_composer"
    case lsTrackCount = "ls_track_count"
    case lsDiscCount = "ls_disc_count"
    case lsCompilation = "ls_compilation"
    case lsBpm = "ls_bpm"
    case lsGrouping = "ls_grouping"
    case lsWork = "ls_work"
    case lsMovement = "ls_movement"
    case lsMovementNumber = "ls_movement_number"
    case lsMovementCount = "ls_movement_count"
    case lsMusicRating = "ls_music_rating"
    case lsMusicFavorited = "ls_music_favorited"
    case lsMusicDisliked = "ls_music_disliked"
    case lsMusicAlbumFavorited = "ls_music_album_favorited"
    case lsMusicAlbumDisliked = "ls_music_album_disliked"
    case lsKind = "ls_kind"
    case lsBitRate = "ls_bit_rate"
    case lsSampleRate = "ls_sample_rate"
    case lsMusicDateAdded = "ls_music_date_added"
    case lsMusicPlayedCount = "ls_music_played_count"
    case lsMusicSkippedCount = "ls_music_skipped_count"
    case lsMusicPlayedDate = "ls_music_played_date"
    case lsPiece = "ls_piece"
    case lsPositionSeconds = "ls_position_seconds"
    case lsState = "ls_state"
    case lsRate = "ls_rate"
    case lsMeasuredAt = "ls_measured_at"
  }

  /// Every key a property above models.
  public static let definedKeys = Set(CodingKeys.allCases.map(\.stringValue))
  /// The now-playing keys a listen must not carry.
  static let nowPlayingOnlyKeys: Set<CodingKeys> = [
    .lsPositionSeconds, .lsState, .lsRate, .lsMeasuredAt,
  ]
  /// The listen keys a now-playing item must not carry.
  static let listenOnlyKeys: Set<CodingKeys> = [.lsPiece]

  /// Info with no key set.
  public init() {}

  /// Whether `key` may not sit in `otherInfo`: a defined key, which its property holds, an
  /// undefined `ls_` key, or the store's own `mbid_mapping`, which a client must never send.
  static func isRefusedOtherKey(_ key: String) -> Bool {
    definedKeys.contains(key) || key.hasPrefix("ls_") || key == "mbid_mapping"
  }

  /// Decode the info, keeping each plain key it does not define in `otherInfo`, and refusing
  /// a key the contract refuses and a null on a defined key.
  public init(from decoder: any Decoder) throws {
    let others = try OpenCodingKey.keys(of: decoder).filter { !Self.definedKeys.contains($0) }
    if let refused = others.sorted().first(where: Self.isRefusedOtherKey) {
      throw OpenCodingKey.refusal("refused key: \(refused)", at: decoder.codingPath)
    }
    try OpenCodingKey.refuseNulls(of: decoder, among: Self.definedKeys)
    let defined = try decoder.container(keyedBy: CodingKeys.self)
    for field in Self.fields {
      try field.decode(defined, &self)
    }
    let open = try decoder.container(keyedBy: OpenCodingKey.self)
    for key in others {
      otherInfo[key] = try open.decode(JSONValue.self, forKey: OpenCodingKey(stringValue: key))
    }
  }

  /// Encode the info, with `otherInfo`'s keys beside the defined ones, refusing an
  /// `otherInfo` key that would shadow a defined key or that the contract refuses.
  public func encode(to encoder: any Encoder) throws {
    if let refused = otherInfo.keys.sorted().first(where: Self.isRefusedOtherKey) {
      throw EncodingError.invalidValue(
        refused,
        .init(codingPath: encoder.codingPath, debugDescription: "refused key: \(refused)"))
    }
    var defined = encoder.container(keyedBy: CodingKeys.self)
    for field in Self.fields {
      try field.encode(self, &defined)
    }
    var open = encoder.container(keyedBy: OpenCodingKey.self)
    for (key, value) in otherInfo {
      try open.encode(value, forKey: OpenCodingKey(stringValue: key))
    }
  }

  /// Throw when this info sets one of `keys`, which the record holding it must not carry.
  func refuseKeys(_ keys: Set<CodingKeys>, at codingPath: [any CodingKey]) throws {
    let carried = Self.fields.filter { keys.contains($0.key) && $0.isSet(self) }
    if let first = carried.map(\.key.stringValue).sorted().first {
      throw OpenCodingKey.refusal("\(first) does not belong in this record", at: codingPath)
    }
  }
}

import Foundation

/// The range the contract gives each integer key a built record may carry.
///
/// No out-of-range value may reach the queue, or the store would refuse that record on every
/// retry. `BoundsTests` holds these ranges equal to the copied schemas, so a contract change
/// to a bound fails a test rather than a queued record.
enum IntegerBound: String, CaseIterable {
  case listenedAt = "listened_at"
  case durationMs = "duration_ms"
  case duration
  case durationPlayed = "duration_played"
  case durationPlayedMs = "duration_played_ms"
  case lsDiscNumber = "ls_disc_number"
  case lsYear = "ls_year"
  case lsTrackCount = "ls_track_count"
  case lsDiscCount = "ls_disc_count"
  case lsBpm = "ls_bpm"
  case lsMovementNumber = "ls_movement_number"
  case lsMovementCount = "ls_movement_count"
  case lsMusicRating = "ls_music_rating"
  case lsBitRate = "ls_bit_rate"
  case lsSampleRate = "ls_sample_rate"
  case lsMusicDateAdded = "ls_music_date_added"
  case lsMusicPlayedCount = "ls_music_played_count"
  case lsMusicSkippedCount = "ls_music_skipped_count"
  case lsMusicPlayedDate = "ls_music_played_date"
  case lsPiece = "ls_piece"

  /// The last second of 9999-12-31 UTC, the ceiling of every Unix-seconds key.
  static let lastSecond = 253_402_300_799
  /// Twenty-four days in seconds, the ceiling of every length and every time heard.
  static let longestSeconds = 2_073_600
  /// Twenty-four days in milliseconds.
  static let longestMilliseconds = 2_073_600_000
  /// The largest signed 32-bit integer, the ceiling of Music's own counts.
  static let largestCount = 2_147_483_647

  /// The key's inclusive range.
  var range: ClosedRange<Int> {
    switch self {
    case .listenedAt: 1_033_430_400...Self.lastSecond
    case .durationMs, .durationPlayedMs: 0...Self.longestMilliseconds
    case .duration, .durationPlayed: 0...Self.longestSeconds
    case .lsDiscNumber, .lsDiscCount, .lsBpm, .lsMovementNumber, .lsMovementCount, .lsPiece:
      1...999
    case .lsYear: 1_000...9_999
    case .lsTrackCount: 1...9_999
    case .lsMusicRating: 0...100
    case .lsBitRate: 1...100_000
    case .lsSampleRate: 1...1_000_000
    case .lsMusicDateAdded, .lsMusicPlayedDate: 0...Self.lastSecond
    case .lsMusicPlayedCount, .lsMusicSkippedCount: 0...Self.largestCount
    }
  }
}

/// The range the contract gives each number key a built record carries.
enum NumberBound: String, CaseIterable {
  case lsPositionSeconds = "ls_position_seconds"
  case lsMeasuredAt = "ls_measured_at"

  /// The key's inclusive range.
  var range: ClosedRange<Double> {
    switch self {
    case .lsPositionSeconds: 0...Double(IntegerBound.longestSeconds)
    case .lsMeasuredAt:
      Double(IntegerBound.listenedAt.range.lowerBound)...Double(IntegerBound.lastSecond)
    }
  }
}

/// Builds the contract's records from an open play, keeping every value inside the
/// contract's bounds.
///
/// The snapshot is preferred and the notice's name, artist and album are the fallback. A
/// track with no artist or no title builds nothing, since the contract requires both and a
/// made-up name would be recorded as if it were real.
public enum RecordBuilder {
  /// The `media_player` every record names.
  static let mediaPlayer = "Music"
  /// The class of a track that is a file on this machine.
  static let fileTrackClass = "file track"
  /// The class of a radio stream.
  static let urlTrackClass = "URL track"
  /// Music's media kinds that have a media type of their own; any other kind is `other`.
  static let mediaTypes: [String: LsMediaType] = [
    "song": .music, "music video": .music, "podcast": .podcast, "audiobook": .audiobook,
  ]
  /// Milliseconds in a second.
  static let millisecondsPerSecond = 1_000.0

  /// Every integer key's range, by key.
  static let bounds = Dictionary(
    uniqueKeysWithValues: IntegerBound.allCases.map { ($0.rawValue, $0.range) })
  /// Every number key's range, by key.
  static let numberBounds = Dictionary(
    uniqueKeysWithValues: NumberBound.allCases.map { ($0.rawValue, $0.range) })

  /// The finished listen of `play`'s current piece; nil when it cannot be recorded.
  public static func listen(_ play: OpenPlay) -> ListenRecord? {
    let heard = IntegerBound.durationPlayed.range
    guard IntegerBound.lsPiece.range.contains(play.piece),
      let listenedAt = wholeSeconds(play.startedAt, in: IntegerBound.listenedAt.range),
      // Capped rather than refused: a play longer than the contract's ceiling still happened.
      let durationPlayed = wholeSeconds(
        min(play.heardSeconds, Double(heard.upperBound)), in: heard),
      var metadata = trackMetadata(play)
    else {
      return nil
    }
    metadata.additionalInfo.durationPlayed = durationPlayed
    metadata.additionalInfo.lsPiece = play.piece
    let listen = Listen(listenedAt: listenedAt, trackMetadata: metadata)
    return ListenRecord(listenType: .single, payload: [listen])
  }

  /// What `play` is doing now, `positionMs` into the track as read at `at`; nil when it
  /// cannot be recorded.
  public static func nowPlaying(_ play: OpenPlay, state: LsState, positionMs: Int, at time: Double)
    -> NowPlayingRecord?
  {
    guard NumberBound.lsMeasuredAt.range.contains(time), var metadata = trackMetadata(play) else {
      return nil
    }
    let seconds = Double(positionMs) / millisecondsPerSecond
    metadata.additionalInfo.lsPositionSeconds = clamped(
      seconds, to: NumberBound.lsPositionSeconds.range)
    metadata.additionalInfo.lsState = state
    metadata.additionalInfo.lsMeasuredAt = time
    return NowPlayingRecord(
      listenType: .playingNow, payload: [NowPlayingItem(trackMetadata: metadata)])
  }

  /// `seconds` rounded down, or nil when that falls outside `range`; NaN is outside every
  /// range, and the check comes before the conversion, which would trap on a huge value.
  static func wholeSeconds(_ seconds: Double, in range: ClosedRange<Int>) -> Int? {
    let whole = seconds.rounded(.down)
    guard whole >= Double(range.lowerBound), whole <= Double(range.upperBound) else {
      return nil
    }
    return Int(whole)
  }

  /// `value` held inside `range`.
  static func clamped(_ value: Double, to range: ClosedRange<Double>) -> Double {
    min(max(value, range.lowerBound), range.upperBound)
  }

  /// `value` when it lies inside `bound`'s range, else nil, so the key is omitted.
  static func bounded(_ value: Int?, _ bound: IntegerBound) -> Int? {
    guard let value, bound.range.contains(value) else { return nil }
    return value
  }

  /// `value` unless it is nil or empty: the contract's text keys need a character.
  static func text(_ value: String?) -> String? {
    guard let value, !value.isEmpty else { return nil }
    return value
  }

  /// The track part both records share; nil without an artist and a title.
  static func trackMetadata(_ play: OpenPlay) -> TrackMetadata? {
    let snap = play.snapshot ?? TrackSnapshot()
    guard let artist = text(snap.artist) ?? text(play.noticeArtist),
      let title = text(snap.name) ?? text(play.noticeName)
    else {
      return nil
    }
    var info = playInfo(play, snap)
    addTags(snap, artist: artist, to: &info)
    addMusicFields(snap, to: &info)
    return TrackMetadata(
      artistName: artist, trackName: title, releaseName: text(snap.album) ?? text(play.noticeAlbum),
      additionalInfo: info)
  }

  /// The client, the player, the play's identity, its length and where the audio came from.
  static func playInfo(_ play: OpenPlay, _ snap: TrackSnapshot) -> AdditionalInfo {
    var info = AdditionalInfo()
    info.submissionClient = Layout.submissionClient
    info.submissionClientVersion = Layout.version
    info.mediaPlayer = mediaPlayer
    info.mediaPlayerVersion = text(snap.musicVersion)
    info.durationMs = bounded(play.durationMs ?? snap.durationMs, .durationMs)
    info.lsPersistentID = text(play.persistentID)
    info.lsPlayID = text(play.playID)
    info.lsMediaType = snap.mediaKind.map { mediaTypes[$0] ?? .other }
    if snap.trackClass == urlTrackClass {
      info.lsSource = .radio
    } else if snap.trackClass == fileTrackClass, let path = text(snap.location) {
      // A local file is recorded with its path, which the contract requires beside it.
      info.lsSource = .localFile
      info.lsFilePath = path
    }
    return info
  }

  /// The tags a player holds for any track. Music's 0 means "none", so a 0 omits the key.
  static func addTags(_ snap: TrackSnapshot, artist: String, to info: inout AdditionalInfo) {
    info.tracknumber = snap.trackNumber.flatMap { $0 > 0 ? String($0) : nil }
    // The album artist is recorded only when it says something the artist does not.
    info.lsAlbumArtist = text(snap.albumArtist).flatMap { $0 == artist ? nil : $0 }
    info.lsDiscNumber = bounded(snap.discNumber, .lsDiscNumber)
    info.lsGenre = text(snap.genre)
    info.lsYear = bounded(snap.year, .lsYear)
    info.lsComposer = text(snap.composer)
    info.lsTrackCount = bounded(snap.trackCount, .lsTrackCount)
    info.lsDiscCount = bounded(snap.discCount, .lsDiscCount)
    info.lsCompilation = snap.compilation
    info.lsBpm = bounded(snap.bpm, .lsBpm)
    info.lsGrouping = text(snap.grouping)
    info.lsWork = text(snap.work)
    info.lsMovement = text(snap.movement)
    info.lsMovementNumber = bounded(snap.movementNumber, .lsMovementNumber)
    info.lsMovementCount = bounded(snap.movementCount, .lsMovementCount)
  }

  /// Music's own opinions, file facts and counts, as read when the play started. A rating
  /// of 0 is kept: it means "unrated", inside the contract's range.
  static func addMusicFields(_ snap: TrackSnapshot, to info: inout AdditionalInfo) {
    info.lsMusicRating = bounded(snap.rating, .lsMusicRating)
    info.lsMusicFavorited = snap.favorited
    info.lsMusicDisliked = snap.disliked
    info.lsMusicAlbumFavorited = snap.albumFavorited
    info.lsMusicAlbumDisliked = snap.albumDisliked
    info.lsKind = text(snap.kind)
    info.lsBitRate = bounded(snap.bitRate, .lsBitRate)
    info.lsSampleRate = bounded(snap.sampleRate, .lsSampleRate)
    info.lsMusicDateAdded = bounded(snap.dateAdded, .lsMusicDateAdded)
    info.lsMusicPlayedCount = bounded(snap.playedCount, .lsMusicPlayedCount)
    info.lsMusicSkippedCount = bounded(snap.skippedCount, .lsMusicSkippedCount)
    info.lsMusicPlayedDate = bounded(snap.playedDate, .lsMusicPlayedDate)
  }
}

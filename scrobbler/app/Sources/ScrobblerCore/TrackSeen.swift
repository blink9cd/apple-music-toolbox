import Foundation

/// A track as one notice or one position read reports it.
struct TrackSeen {
  /// The track's persistent ID, normalized.
  let persistentID: String
  /// Playing or paused; a stopped player reports no track.
  let state: PlayerState
  /// The position, when the input was a read.
  let positionMs: Int?
  /// The track length, when the input carried one.
  let durationMs: Int?
  /// The notice's track name, the fallback when there is no snapshot.
  var name: String?
  /// The notice's artist.
  var artist: String?
  /// The notice's album.
  var album: String?
}

extension TrackSeen {
  /// The start of the track, in milliseconds, that a read back into counts as a repeat.
  static let repeatWindowMs = Int(Engine.repeatWindow * Engine.millisecondsPerSecond)

  /// Whether this read went back into the repeat window from a position past it.
  func isRepeat(of play: OpenPlay) -> Bool {
    guard let new = positionMs, let old = play.lastPositionMs else { return false }
    return new <= Self.repeatWindowMs && old > Self.repeatWindowMs
  }

  /// This report with the closing play's notice fallbacks where it has none: a repeat is
  /// the same track, so its names still hold.
  func filling(from play: OpenPlay?) -> TrackSeen {
    var filled = self
    filled.name = name ?? play?.noticeName
    filled.artist = artist ?? play?.noticeArtist
    filled.album = album ?? play?.noticeAlbum
    return filled
  }
}

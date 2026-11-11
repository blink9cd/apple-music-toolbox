import Foundation

/// The three states Music reports; any other report is not a state the scrobbler acts on.
public enum PlayerState: String, Sendable, Equatable {
  case playing, paused, stopped
}

/// One `com.apple.Music.playerInfo` notice, reduced to the fields the scrobbler reads.
///
/// The notice only signals that something changed; the snapshot read is what a play is
/// recorded from, so every field but the state is optional and a wrongly typed one is
/// dropped rather than failing the notice.
public struct PlayerNotice: Sendable, Equatable {
  /// What the player is doing.
  public var state: PlayerState
  /// The track's persistent ID, normalized to 16 uppercase hex digits.
  public var persistentID: String?
  /// The track's name.
  public var name: String?
  /// The track's artist.
  public var artist: String?
  /// The track's album.
  public var album: String?
  /// The track's length in milliseconds.
  public var totalTimeMs: Int?

  /// The playerInfo notice's userInfo; nil when the state key is missing or unknown.
  public static func parse(_ userInfo: [AnyHashable: Any]) -> PlayerNotice? {
    guard let stateText = userInfo[AnyHashable("Player State")] as? String,
      let state = PlayerState(rawValue: stateText.lowercased())
    else {
      return nil
    }
    return PlayerNotice(
      state: state,
      persistentID: PersistentID.normalize(userInfo[AnyHashable("Persistent ID")]),
      name: FieldText.capped(userInfo[AnyHashable("Name")] as? String),
      artist: FieldText.capped(userInfo[AnyHashable("Artist")] as? String),
      album: FieldText.capped(userInfo[AnyHashable("Album")] as? String),
      totalTimeMs: milliseconds(userInfo[AnyHashable("Total Time")]))
  }

  /// A whole, non-negative number of milliseconds, or nil.
  private static func milliseconds(_ value: Any?) -> Int? {
    guard let millis = value as? Int, millis >= 0 else {
      return nil
    }
    return millis
  }
}

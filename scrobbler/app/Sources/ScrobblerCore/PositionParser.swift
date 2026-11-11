/// Where the player is: the position read's result.
public struct PositionRead: Sendable, Equatable {
  /// What the player is doing.
  public var state: PlayerState
  /// How far into the track the player is, in milliseconds; 0 when stopped.
  public var positionMs: Int
  /// The current track's length in milliseconds, when Music gave one.
  public var durationMs: Int?
  /// The current track's persistent ID, normalized; nil when stopped.
  public var persistentID: String?
}

/// Reads the position script's result into a `PositionRead`.
public enum PositionParser {
  /// The fields a playing or paused result carries: state, position, duration and ID.
  static let fieldCount = 4

  /// The position result; an empty result means Music is not running.
  public static func parse(_ text: String) -> Result<PositionRead, SnapshotReadError> {
    if text.isEmpty {
      return .failure(.musicNotRunning)
    }
    let pieces = FieldText.split(text)
    guard let state = PlayerState(rawValue: String(pieces[0])) else {
      return .failure(.malformed("unknown player state"))
    }
    do {
      return .success(try read(pieces, state: state))
    } catch {
      return .failure(error)
    }
  }

  /// The fields after the state, which Music writes only while a track is current.
  private static func read(_ pieces: [Substring], state: PlayerState) throws(SnapshotReadError)
    -> PositionRead
  {
    if state == .stopped {
      guard pieces.count == 1 else {
        throw .malformed("expected 1 field for stopped, got \(pieces.count)")
      }
      return PositionRead(state: .stopped, positionMs: 0, durationMs: nil, persistentID: nil)
    }
    guard pieces.count == fieldCount else {
      throw .malformed("expected \(fieldCount) fields, got \(pieces.count)")
    }
    // The position is the one field a playing or paused player always has.
    guard let position = try FieldText.count(pieces[1], label: "position") else {
      throw .malformed("position: expected a non-negative integer")
    }
    return PositionRead(
      state: state, positionMs: position,
      durationMs: try FieldText.count(pieces[2], label: "duration"),
      persistentID: try FieldText.persistentID(pieces[3], label: "persistentID"))
  }
}

/// How one snapshot field's text is read back.
enum FieldKind: Sendable {
  /// Kept as Music wrote it.
  case text
  /// A persistent ID, normalized to 16 uppercase hex digits.
  case persistentID
  /// A whole number that cannot be negative: a count, a number, a rate or a length.
  case count
  /// A local date as `Y/M/D/S`, read into seconds since 1970 in a given time zone.
  case date
  /// `true` or `false`.
  case flag
}

/// The fields the snapshot read returns, in the order the script writes them.
///
/// Each case carries its AppleScript expression, so the script and the parser are built
/// from this one ordered list and cannot drift apart.
public enum SnapshotField: String, CaseIterable, Sendable {
  case persistentID, trackClass, location, name, artist, album, albumArtist, composer, genre
  case year, trackNumber, trackCount, discNumber, discCount, compilation, bpm, grouping, work
  case movement, movementNumber, movementCount, rating, favorited, disliked, albumFavorited
  case albumDisliked, kind, bitRate, sampleRate, dateAdded, playedCount, skippedCount
  case playedDate, mediaKind, durationMs, musicVersion

  /// The AppleScript expression reading this field of the current track `t`.
  public var expression: String {
    switch self {
    case .persistentID: "persistent ID of t"
    case .trackClass: "class of t"
    case .location: "my posixLocation(t)"
    case .dateAdded: "my dateParts(date added of t)"
    case .playedDate: "my dateParts(played date of t)"
    case .durationMs: "my milliseconds(duration of t)"
    // Read inside the tell block, so this is the app's version, not the track's.
    case .musicVersion: "version"
    default: "\(Self.words(of: rawValue)) of t"
    }
  }

  /// How the parser reads this field's text.
  var kind: FieldKind {
    switch self {
    case .persistentID: .persistentID
    case .year, .trackNumber, .trackCount, .discNumber, .discCount, .bpm, .movementNumber,
      .movementCount, .rating, .bitRate, .sampleRate, .playedCount, .skippedCount, .durationMs:
      .count
    case .dateAdded, .playedDate: .date
    case .compilation, .favorited, .disliked, .albumFavorited, .albumDisliked: .flag
    default: .text
    }
  }

  /// A camel-case name as AppleScript's lowercase words: `albumArtist` is `album artist`.
  private static func words(of name: String) -> String {
    name.reduce(into: "") { spelled, letter in
      spelled += letter.isUppercase ? " \(letter.lowercased())" : String(letter)
    }
  }
}

/// The source text of the two AppleScript reads; this task only builds it, never runs it.
///
/// Both scripts return their fields joined by `separator`, and an empty string when Music
/// is not running, so asking never launches Music.
public enum MusicScripts {
  /// The ASCII unit separator, which no track field can contain.
  public static let separator: Character = "\u{1F}"

  /// The snapshot read: every `SnapshotField` of the current track, in order.
  ///
  /// A stopped player has no current track, so the script then returns just `stopped`.
  public static func snapshotSource() -> String {
    let reads = SnapshotField.allCases.map {
      "      set end of out to (\($0.expression)) as text\n"
    }
    return handlers + snapshotOpening + reads.joined() + closing
  }

  /// The position read: the player state, then the position, the duration and the ID.
  ///
  /// Music has no current track while stopped, so for that state the script returns just
  /// the state.
  public static let positionSource =
    handlers + """
      if application "Music" is running then
        with timeout of 5 seconds
          tell application "Music"
            set s to (player state) as text
            if player state is stopped then return s
            set out to {s}
            set end of out to (my milliseconds(player position)) as text
            set end of out to (my milliseconds(duration of current track)) as text
            set end of out to (persistent ID of current track) as text

      """ + closing

  /// The handlers both scripts share.
  ///
  /// A date leaves as its local parts, `Y/M/D/S` with S the seconds since midnight, because
  /// AppleScript's integers stop at 536870911, so epoch seconds would come back in exponent
  /// form, and date subtraction ignores daylight saving; the parser does the arithmetic.
  /// The location handler is called only after the running check, so its Music tell block
  /// cannot launch Music; outside one, `file track` and `location` are not Music's terms.
  private static let handlers = """
    on dateParts(d)
      if d is missing value then return ""
      set ymd to (year of d) as text & "/" & ((month of d) as integer) & "/" & (day of d)
      return ymd & "/" & (time of d)
    end dateParts
    on posixLocation(t)
      tell application "Music"
        if class of t is not file track then return ""
        set l to location of t
      end tell
      if l is missing value then return ""
      return POSIX path of l
    end posixLocation
    on milliseconds(s)
      -- A 149-hour ceiling: from 536870 seconds on, the millisecond count overflows
      -- AppleScript's integers, so a longer length reads as empty.
      if s is missing value then return ""
      if s is greater than or equal to 536870 then return ""
      return (round (s * 1000)) as text
    end milliseconds

    """

  /// The snapshot script up to its per-field reads.
  private static let snapshotOpening = """
    if application "Music" is running then
      with timeout of 5 seconds
        tell application "Music"
          if player state is stopped then return "stopped"
          set t to current track
          set out to {}

    """

  /// Both scripts' ending: join the fields, and return "" when Music is not running.
  private static let closing = """
          set AppleScript's text item delimiters to (character id 31)
          return out as text
        end tell
      end with timeout
    end if
    return ""

    """
}

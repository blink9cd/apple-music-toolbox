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
  /// The ASCII unit separator. A text field may hold one, so the snapshot escapes it.
  public static let separator: Character = "\u{1F}"

  /// The snapshot read: every `SnapshotField` of the current track, in order.
  ///
  /// Each text field is escaped (`escapeHandler`); the other fields are numbers, flags,
  /// dates and an ID, which cannot hold a character it escapes. A stopped player has no
  /// current track, so the script then returns just `stopped`.
  public static func snapshotSource() -> String {
    let reads = SnapshotField.allCases.map { field in
      let read = "(\(field.expression)) as text"
      return "      set end of out to \(field.kind == .text ? "my escapedText(\(read))" : read)\n"
    }
    return handlers + escapeHandler + snapshotOpening + reads.joined() + closing
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

  /// The snapshot's escape: each percent sign, carriage return, linefeed, tab and U+001F
  /// in a text field becomes a percent sign and its two hex digits, which
  /// `FieldText.unescaped` undoes, so a title holding the separator neither splits the
  /// result nor loses a character.
  ///
  /// Percent-encoding just these five, rather than a backslash escape or a length prefix,
  /// keeps the common case to one text-item split and join a character. AppleScript's
  /// text-item search works on whole characters (grapheme clusters), though, so a
  /// delimiter followed by a combining mark or a variation selector is passed by; the
  /// handler then reads the text's code points and, when one of the four controls is
  /// still there, rebuilds the text from them with each escaped. A percent sign fused
  /// with a following mark is left as it is, and the parser keeps a sign that begins no
  /// escape, so that text still reads back. The text is the one the Python listing
  /// scripts share (tag_refresh's `script_text.ESCAPE_HANDLER`), held equal to it by
  /// tag_refresh's `test_script_text.py`, whose sibling suite runs this copy through
  /// `osascript`.
  private static let escapeHandler = """
    on escapedText(theText)
      if theText is missing value then return ""
      set savedDelimiters to AppleScript's text item delimiters
      set escapePairs to {{"%", "%25"}, {return & linefeed, "%0D%0A"}}
      set escapePairs to escapePairs & {{return, "%0D"}, {linefeed, "%0A"}}
      set escapePairs to escapePairs & {{tab, "%09"}, {character id 31, "%1F"}}
      repeat with escapePair in escapePairs
        set AppleScript's text item delimiters to item 1 of escapePair
        set theParts to text items of theText
        set AppleScript's text item delimiters to item 2 of escapePair
        set theText to theParts as text
      end repeat
      set AppleScript's text item delimiters to savedDelimiters
      set codePoints to id of theText
      if class of codePoints is not list then set codePoints to {codePoints}
      if codePoints contains 9 or codePoints contains 10 then return my escapedPoints(codePoints)
      if codePoints contains 13 or codePoints contains 31 then return my escapedPoints(codePoints)
      return theText
    end escapedText

    on escapedPoints(codePoints)
      if codePoints is {} then return ""
      script pointStore
        property pts : codePoints
        property outs : {}
      end script
      repeat with i from 1 to count of pointStore's pts
        set pointValue to item i of pointStore's pts
        if pointValue is 9 then
          set end of pointStore's outs to 37
          set end of pointStore's outs to 48
          set end of pointStore's outs to 57
        else if pointValue is 10 then
          set end of pointStore's outs to 37
          set end of pointStore's outs to 48
          set end of pointStore's outs to 65
        else if pointValue is 13 then
          set end of pointStore's outs to 37
          set end of pointStore's outs to 48
          set end of pointStore's outs to 68
        else if pointValue is 31 then
          set end of pointStore's outs to 37
          set end of pointStore's outs to 49
          set end of pointStore's outs to 70
        else
          set end of pointStore's outs to pointValue
        end if
      end repeat
      return string id (pointStore's outs)
    end escapedPoints

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
      end timeout
    end if
    return ""

    """
}

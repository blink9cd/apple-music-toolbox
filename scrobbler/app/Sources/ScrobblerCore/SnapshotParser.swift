import Foundation

/// Why a read of Music produced no usable result.
public enum SnapshotReadError: Error, Equatable {
  /// The script returned nothing, which it does only when Music is not running.
  case musicNotRunning
  /// The system refused to let the scrobbler script Music; the live bridge reports this,
  /// never a parser.
  case automationDenied
  /// The result did not have the shape the script writes; the text says which part.
  case malformed(String)
  /// Music is running but stopped, so there is no current track to read.
  case noCurrentTrack
}

/// The current track as the snapshot read returns it: one property per `SnapshotField`,
/// each nil when Music left it empty. It is Codable so an open play can be saved with it.
public struct TrackSnapshot: Codable, Sendable, Equatable {
  /// The track's persistent ID, normalized to 16 uppercase hex digits.
  public var persistentID: String?
  /// The track's AppleScript class, such as `file track` or `URL track`.
  public var trackClass: String?
  /// The file's POSIX path; nil for anything but a file track.
  public var location: String?
  /// The track's name.
  public var name: String?
  /// The track's artist.
  public var artist: String?
  /// The track's album.
  public var album: String?
  /// The album's artist.
  public var albumArtist: String?
  /// The track's composer.
  public var composer: String?
  /// The track's genre.
  public var genre: String?
  /// The release year; Music writes 0 when it has none.
  public var year: Int?
  /// The track's number on its disc.
  public var trackNumber: Int?
  /// How many tracks the disc has.
  public var trackCount: Int?
  /// The disc's number in the album.
  public var discNumber: Int?
  /// How many discs the album has.
  public var discCount: Int?
  /// Whether the track is part of a compilation.
  public var compilation: Bool?
  /// The track's beats per minute.
  public var bpm: Int?
  /// The track's grouping.
  public var grouping: String?
  /// The classical work the track belongs to.
  public var work: String?
  /// The movement's name within its work.
  public var movement: String?
  /// The movement's number within its work.
  public var movementNumber: Int?
  /// How many movements the work has.
  public var movementCount: Int?
  /// The track's rating, 0 to 100.
  public var rating: Int?
  /// Whether the track is marked as a favorite.
  public var favorited: Bool?
  /// Whether the track is marked as disliked.
  public var disliked: Bool?
  /// Whether the track's album is marked as a favorite.
  public var albumFavorited: Bool?
  /// Whether the track's album is marked as disliked.
  public var albumDisliked: Bool?
  /// The file kind Music shows, such as `AAC audio file`.
  public var kind: String?
  /// The bit rate in kilobits per second.
  public var bitRate: Int?
  /// The sample rate in hertz.
  public var sampleRate: Int?
  /// When the track was added, as Unix seconds.
  public var dateAdded: Int?
  /// How many times the track has been played.
  public var playedCount: Int?
  /// How many times the track has been skipped.
  public var skippedCount: Int?
  /// When the track was last played, as Unix seconds.
  public var playedDate: Int?
  /// The media kind, such as `song`.
  public var mediaKind: String?
  /// The track's length in milliseconds; nil past the 149-hour ceiling the script applies.
  public var durationMs: Int?
  /// Music's own version, read alongside the track.
  public var musicVersion: String?

  /// A snapshot with every field empty.
  public init() {}

  /// Every property from its parsed field.
  init(_ fields: ParsedFields) {
    persistentID = fields.text(.persistentID)
    trackClass = fields.text(.trackClass)
    location = fields.text(.location)
    name = fields.text(.name)
    artist = fields.text(.artist)
    album = fields.text(.album)
    albumArtist = fields.text(.albumArtist)
    composer = fields.text(.composer)
    genre = fields.text(.genre)
    year = fields.number(.year)
    trackNumber = fields.number(.trackNumber)
    trackCount = fields.number(.trackCount)
    discNumber = fields.number(.discNumber)
    discCount = fields.number(.discCount)
    compilation = fields.flag(.compilation)
    bpm = fields.number(.bpm)
    grouping = fields.text(.grouping)
    work = fields.text(.work)
    movement = fields.text(.movement)
    movementNumber = fields.number(.movementNumber)
    movementCount = fields.number(.movementCount)
    rating = fields.number(.rating)
    favorited = fields.flag(.favorited)
    disliked = fields.flag(.disliked)
    albumFavorited = fields.flag(.albumFavorited)
    albumDisliked = fields.flag(.albumDisliked)
    kind = fields.text(.kind)
    bitRate = fields.number(.bitRate)
    sampleRate = fields.number(.sampleRate)
    dateAdded = fields.number(.dateAdded)
    playedCount = fields.number(.playedCount)
    skippedCount = fields.number(.skippedCount)
    playedDate = fields.number(.playedDate)
    mediaKind = fields.text(.mediaKind)
    durationMs = fields.number(.durationMs)
    musicVersion = fields.text(.musicVersion)
  }
}

/// One field's value once its text has been read by its kind.
enum FieldValue: Equatable {
  case text(String)
  case number(Int)
  case flag(Bool)
}

/// Every non-empty field of one snapshot result, already checked against its kind.
struct ParsedFields {
  let values: [SnapshotField: FieldValue]

  /// The field's text, or nil when it was empty.
  func text(_ field: SnapshotField) -> String? {
    guard case .text(let value)? = values[field] else { return nil }
    return value
  }

  /// The field's number, or nil when it was empty.
  func number(_ field: SnapshotField) -> Int? {
    guard case .number(let value)? = values[field] else { return nil }
    return value
  }

  /// The field's flag, or nil when it was empty.
  func flag(_ field: SnapshotField) -> Bool? {
    guard case .flag(let value)? = values[field] else { return nil }
    return value
  }
}

/// Reads the snapshot script's result into a `TrackSnapshot`.
public enum SnapshotParser {
  /// What the script returns in place of the fields when the player is stopped.
  static let stoppedResult = "stopped"

  /// The snapshot result; an empty result means Music is not running.
  ///
  /// The two dates arrive as local parts, so `timeZone` is the zone Music read them in:
  /// the machine's own unless a test pins one.
  public static func parse(_ text: String, timeZone: TimeZone = .current)
    -> Result<TrackSnapshot, SnapshotReadError>
  {
    if text.isEmpty {
      return .failure(.musicNotRunning)
    }
    if text == stoppedResult {
      return .failure(.noCurrentTrack)
    }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = timeZone
    let pieces = FieldText.split(text)
    let fields = SnapshotField.allCases
    guard pieces.count == fields.count else {
      return .failure(.malformed("expected \(fields.count) fields, got \(pieces.count)"))
    }
    var values: [SnapshotField: FieldValue] = [:]
    for (field, piece) in zip(fields, pieces) {
      do {
        values[field] = try read(piece, as: field, calendar: calendar)
      } catch {
        return .failure(error)
      }
    }
    return .success(TrackSnapshot(ParsedFields(values: values)))
  }

  /// One field's text read by its kind; nil when empty.
  private static func read(_ piece: Substring, as field: SnapshotField, calendar: Calendar)
    throws(SnapshotReadError) -> FieldValue?
  {
    let label = field.rawValue
    switch field.kind {
    case .text:
      return piece.isEmpty ? nil : FieldText.capped(String(piece)).map(FieldValue.text)
    case .persistentID:
      return try FieldText.persistentID(piece, label: label).map(FieldValue.text)
    case .count:
      return try FieldText.count(piece, label: label).map(FieldValue.number)
    case .date:
      return try DateParts.seconds(piece, label: label, calendar: calendar).map(FieldValue.number)
    case .flag:
      return try FieldText.flag(piece, label: label).map(FieldValue.flag)
    }
  }
}

/// The per-field readers both result parsers share.
///
/// Each returns nil for an empty field, and for AppleScript's `missing value`, which is what
/// a missing number or flag turns into as text; a real value of the wrong shape throws.
enum FieldText {
  /// The text AppleScript writes for a value Music does not have.
  static let missingValue = "missing value"
  /// The longest text field kept, in UTF-8 bytes. Four times the longest path macOS opens
  /// (1024 bytes), so any real name, artist or location fits; a longer field, which any
  /// process can post in a forged notice, is dropped rather than carried into every save
  /// and record.
  static let maxTextBytes = 4096

  /// `text`, or nil when it is longer than `maxTextBytes`.
  static func capped(_ text: String?) -> String? {
    guard let text, text.utf8.count <= maxTextBytes else { return nil }
    return text
  }

  /// The result's fields, keeping empty ones so the count stays exact.
  static func split(_ text: String) -> [Substring] {
    text.split(separator: MusicScripts.separator, omittingEmptySubsequences: false)
  }

  /// A whole number that cannot be negative.
  static func count(_ piece: Substring, label: String) throws(SnapshotReadError) -> Int? {
    let expected = "a non-negative integer"
    guard let value = try integer(piece, label: label, expected: expected) else { return nil }
    guard value >= 0 else { throw .malformed("\(label): expected \(expected)") }
    return value
  }

  /// A whole number; `expected` names the shape in the error.
  private static func integer(_ piece: Substring, label: String, expected: String)
    throws(SnapshotReadError) -> Int?
  {
    if isAbsent(piece) { return nil }
    guard let value = Int(piece) else { throw .malformed("\(label): expected \(expected)") }
    return value
  }

  /// `true` or `false`, exactly as AppleScript writes them.
  static func flag(_ piece: Substring, label: String) throws(SnapshotReadError) -> Bool? {
    if isAbsent(piece) { return nil }
    switch piece {
    case "true": return true
    case "false": return false
    default: throw .malformed("\(label): expected true or false")
    }
  }

  /// A persistent ID normalized to 16 uppercase hex digits.
  static func persistentID(_ piece: Substring, label: String) throws(SnapshotReadError)
    -> String?
  {
    if isAbsent(piece) { return nil }
    guard let value = PersistentID.normalize(String(piece)) else {
      throw .malformed("\(label): expected 1 to 16 hex digits")
    }
    return value
  }

  /// Whether a typed field holds no value.
  static func isAbsent(_ piece: Substring) -> Bool {
    piece.isEmpty || piece == missingValue
  }
}

/// Reads a date's local parts, `Y/M/D/S` with S the seconds since midnight, into seconds
/// since 1970.
enum DateParts {
  /// The last year read; it keeps every date well inside the range an `Int` of seconds holds.
  static let latestYear = 9999
  /// The seconds in a day, so S runs from 0 to one less.
  static let secondsPerDay = 86400
  /// The seconds in an hour.
  static let secondsPerHour = 3600
  /// The seconds in a minute.
  static let secondsPerMinute = 60

  /// The parts as seconds since 1970, the local time read in `calendar`'s zone.
  static func seconds(_ piece: Substring, label: String, calendar: Calendar)
    throws(SnapshotReadError) -> Int?
  {
    if FieldText.isAbsent(piece) { return nil }
    guard let date = date(from: piece, calendar: calendar) else {
      throw .malformed("\(label): expected Y/M/D/S")
    }
    return Int(date.timeIntervalSince1970)
  }

  /// The parts as a date, or nil for any other shape or a day the month does not have.
  ///
  /// A time the fall-back hour repeats takes Calendar's first match, the earlier instant; a
  /// time the spring-forward gap skips is moved past the gap by Calendar.
  private static func date(from piece: Substring, calendar: Calendar) -> Date? {
    let parts = piece.split(separator: "/", omittingEmptySubsequences: false).compactMap {
      Int($0)
    }
    guard parts.count == 4, (1...latestYear).contains(parts[0]), (1...12).contains(parts[1]),
      (1...31).contains(parts[2]), (0..<secondsPerDay).contains(parts[3])
    else {
      return nil
    }
    let wanted = DateComponents(year: parts[0], month: parts[1], day: parts[2])
    var moment = wanted
    moment.hour = parts[3] / secondsPerHour
    moment.minute = parts[3] % secondsPerHour / secondsPerMinute
    moment.second = parts[3] % secondsPerMinute
    // Calendar rolls an impossible day (February 30) into the next month, so a date whose
    // own day differs from the one asked for was never a real date.
    guard let date = calendar.date(from: moment),
      calendar.dateComponents([.year, .month, .day], from: date) == wanted
    else {
      return nil
    }
    return date
  }
}

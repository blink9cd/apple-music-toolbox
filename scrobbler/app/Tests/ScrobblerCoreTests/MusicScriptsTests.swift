import Testing

@testable import ScrobblerCore

@Test func scriptAndParserShareOneFieldOrder() {
  let source = MusicScripts.snapshotSource()
  var cursor = source.startIndex
  for field in SnapshotField.allCases {
    let found = source.range(of: field.expression, range: cursor..<source.endIndex)
    #expect(found != nil, "\(field) missing or out of order")
    if let found { cursor = found.upperBound }
  }
  #expect(source.contains("if application \"Music\" is running then"))
  #expect(source.contains("with timeout of 5 seconds"))
}

@Test func snapshotScriptReadsEachFieldOnItsOwnLineInOrder() {
  let reads = MusicScripts.snapshotSource().split(separator: "\n")
    .filter { $0.contains("set end of out to") }
    .map { String($0) }
  let expected = SnapshotField.allCases.map {
    "      set end of out to (\($0.expression)) as text"
  }
  #expect(reads == expected)
  #expect(reads.count == 36)
}

/// The three handlers, verbatim, as both scripts' agreed text opens with them.
private let expectedHandlers = """
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

@Test func snapshotScriptMatchesTheAgreedText() {
  let reads = SnapshotField.allCases.map {
    "      set end of out to (\($0.expression)) as text\n"
  }
  let expected =
    expectedHandlers + """
      if application "Music" is running then
        with timeout of 5 seconds
          tell application "Music"
            if player state is stopped then return "stopped"
            set t to current track
            set out to {}

      """ + reads.joined() + """
            set AppleScript's text item delimiters to (character id 31)
            return out as text
          end tell
        end with timeout
      end if
      return ""

      """
  #expect(MusicScripts.snapshotSource() == expected)
}

@Test func positionScriptMatchesTheAgreedText() {
  let expected =
    expectedHandlers + """
      if application "Music" is running then
        with timeout of 5 seconds
          tell application "Music"
            set s to (player state) as text
            if player state is stopped then return s
            set out to {s}
            set end of out to (my milliseconds(player position)) as text
            set end of out to (my milliseconds(duration of current track)) as text
            set end of out to (persistent ID of current track) as text
            set AppleScript's text item delimiters to (character id 31)
            return out as text
          end tell
        end with timeout
      end if
      return ""

      """
  #expect(MusicScripts.positionSource == expected)
}

@Test func locationHandlerTestsTheClassInsideAMusicTellBlock() throws {
  // Outside a Music tell block, `file track` and `location` are not Music's terms and the
  // handler fails to compile, so the class test and the read must sit inside one.
  let source = MusicScripts.snapshotSource()
  let handler = try #require(source.range(of: "on posixLocation(t)"))
  let end = try #require(
    source.range(of: "end posixLocation", range: handler.upperBound..<source.endIndex))
  let body = source[handler.upperBound..<end.lowerBound]
  let tell = try #require(body.range(of: "tell application \"Music\""))
  let classTest = try #require(body.range(of: "if class of t is not file track"))
  let read = try #require(body.range(of: "set l to location of t"))
  let endTell = try #require(body.range(of: "end tell"))
  let posix = try #require(body.range(of: "return POSIX path of l"))
  #expect(tell.upperBound <= classTest.lowerBound)
  #expect(read.upperBound <= endTell.lowerBound)
  #expect(endTell.upperBound <= posix.lowerBound)
}

@Test func neitherScriptUsesTheDeprecatedAsciiCharacterCommand() {
  #expect(!MusicScripts.snapshotSource().contains("ASCII character"))
  #expect(!MusicScripts.positionSource.contains("ASCII character"))
}

@Test func fieldExpressionsMatchTheAgreedReads() {
  #expect(SnapshotField.bpm.expression == "bpm of t")
  #expect(SnapshotField.dateAdded.expression == "my dateParts(date added of t)")
  #expect(SnapshotField.playedDate.expression == "my dateParts(played date of t)")
  #expect(SnapshotField.durationMs.expression == "my milliseconds(duration of t)")
  #expect(SnapshotField.location.expression == "my posixLocation(t)")
  #expect(SnapshotField.musicVersion.expression == "version")
  #expect(Set(SnapshotField.allCases.map(\.expression)).count == SnapshotField.allCases.count)
}

@Test func everyFieldReadsTheTrackPropertyItNames() {
  let expected = [
    "persistent ID of t", "class of t", "my posixLocation(t)", "name of t", "artist of t",
    "album of t", "album artist of t", "composer of t", "genre of t", "year of t",
    "track number of t", "track count of t", "disc number of t", "disc count of t",
    "compilation of t", "bpm of t", "grouping of t", "work of t", "movement of t",
    "movement number of t", "movement count of t", "rating of t", "favorited of t",
    "disliked of t", "album favorited of t", "album disliked of t", "kind of t", "bit rate of t",
    "sample rate of t", "my dateParts(date added of t)", "played count of t",
    "skipped count of t", "my dateParts(played date of t)", "media kind of t",
    "my milliseconds(duration of t)", "version",
  ]
  #expect(SnapshotField.allCases.map(\.expression) == expected)
}

@Test func separatorIsTheAsciiUnitSeparator() {
  #expect(MusicScripts.separator.asciiValue == 31)
}

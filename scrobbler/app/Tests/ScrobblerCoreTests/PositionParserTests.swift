import Testing

@testable import ScrobblerCore

/// One position result line from its fields.
private func positionLine(_ fields: String...) -> String {
  fields.joined(separator: String(MusicScripts.separator))
}

@Test func playingPositionParses() {
  #expect(
    PositionParser.parse(positionLine("playing", "61500", "214000", "0a1b2c3d4e5f6071"))
      == .success(
        PositionRead(
          state: .playing, positionMs: 61500, durationMs: 214000,
          persistentID: "0A1B2C3D4E5F6071")))
}

@Test func pausedPositionWithEmptyDurationAndIDParses() {
  #expect(
    PositionParser.parse(positionLine("paused", "0", "", ""))
      == .success(PositionRead(state: .paused, positionMs: 0, durationMs: nil, persistentID: nil)))
}

@Test func stoppedIsJustTheState() {
  #expect(
    PositionParser.parse("stopped")
      == .success(PositionRead(state: .stopped, positionMs: 0, durationMs: nil, persistentID: nil)))
  #expect(
    PositionParser.parse(positionLine("stopped", "0"))
      == .failure(.malformed("expected 1 field for stopped, got 2")))
}

@Test func emptyPositionResultMeansMusicIsNotRunning() {
  #expect(PositionParser.parse("") == .failure(.musicNotRunning))
}

@Test func unknownStateIsMalformed() {
  #expect(
    PositionParser.parse(positionLine("fast forwarding", "1", "2", "AB"))
      == .failure(.malformed("unknown player state")))
}

@Test func wrongPositionFieldCountIsMalformed() {
  #expect(
    PositionParser.parse(positionLine("playing", "1"))
      == .failure(.malformed("expected 4 fields, got 2")))
}

@Test func badPositionNumbersAreMalformed() {
  #expect(
    PositionParser.parse(positionLine("playing", "", "214000", "AB"))
      == .failure(.malformed("position: expected a non-negative integer")))
  #expect(
    PositionParser.parse(positionLine("playing", "-1", "214000", "AB"))
      == .failure(.malformed("position: expected a non-negative integer")))
  #expect(
    PositionParser.parse(positionLine("playing", "1", "long", "AB"))
      == .failure(.malformed("duration: expected a non-negative integer")))
}

@Test func badPositionPersistentIDIsMalformed() {
  #expect(
    PositionParser.parse(positionLine("playing", "1", "2", "zz"))
      == .failure(.malformed("persistentID: expected 1 to 16 hex digits")))
}

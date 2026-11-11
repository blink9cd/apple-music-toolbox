import Foundation
import Testing

@testable import ScrobblerCore

// The replay command, against the committed sample and against small invented traces.

/// The hand-check sample beside the package.
private let samplesDir = scrobblerDir.appendingPathComponent("samples")

/// An invented track's notice, as one trace line's JSON.
private func noticeLine(at time: Double, _ state: String, id: String = trackOne) -> String {
  """
  {"at": \(time), "notice": {"Player State": "\(state)", "Persistent ID": "\(id)", \
  "Name": "Paper Comet", "Artist": "Velvet Marsh", "Album": "Tin Harbor", "Total Time": 214000}}
  """
}

/// A position read's text as one trace line's JSON.
private func positionLine(at time: Double, _ text: String) -> String {
  #"{"at": \#(time), "position": "\#(text)"}"#
}

/// A playing position read of `id` at `positionMs`, in the position script's form.
private func playingAt(_ positionMs: Int, id: String = trackOne) -> String {
  "playing\\u001f\(positionMs)\\u001f214000\\u001f\(id)"
}

/// `lines` written as a trace in `temp`, returning its file.
private func writeTrace(_ lines: [String], in temp: TempFolder) throws -> URL {
  let file = temp.child("trace.jsonl")
  try Data((lines.joined(separator: "\n") + "\n").utf8).write(to: file)
  return file
}

/// Replay `lines`, returning the records written and the output folder's file names.
private func replay(_ lines: [String]) throws -> (Int, [String]) {
  let temp = try TempFolder()
  let out = temp.child("out")
  let count = try Replay.run(trace: try writeTrace(lines, in: temp), out: out)
  let written = FileManager.default.fileExists(atPath: out.path) ? try names(in: out) : []
  return (count, written)
}

/// The error replaying `lines` throws.
private func replayError(_ lines: [String]) throws -> ReplayError {
  do {
    _ = try replay(lines)
  } catch let error as ReplayError {
    return error
  }
  Issue.record("the replay did not fail")
  throw ReplayError.badLine(0, "no failure")
}

@Test func theSampleTraceReplaysToTheExpectedFilesByteForByte() throws {
  let temp = try TempFolder()
  let out = temp.child("out")
  let expectedDir = samplesDir.appendingPathComponent("expected")
  let count = try Replay.run(trace: samplesDir.appendingPathComponent("trace.jsonl"), out: out)
  let expected = try names(in: expectedDir)
  #expect(try names(in: out) == expected)
  #expect(count == expected.count)
  for name in expected {
    let got = try Data(contentsOf: out.appendingPathComponent(name))
    #expect(got == (try Data(contentsOf: expectedDir.appendingPathComponent(name))), "\(name)")
  }
}

@Test func aPlayHeardPastTheFloorIsWrittenWithASeededPlayID() throws {
  let base = 1_793_000_000.0
  let (count, written) = try replay([
    noticeLine(at: base, "Playing"),
    positionLine(at: base + 2, playingAt(2_000)),
    positionLine(at: base + 4, playingAt(4_000)),
    #"{"at": \#(base + 5), "quit": true}"#,
  ])
  #expect(count == 1)
  #expect(written == ["1793000000-\(playID(1))-001.json"])
}

@Test func anEmptyPositionReadIsMusicQuittingAndAMalformedOneIsSkipped() throws {
  let base = 1_793_000_000.0
  let (count, _) = try replay([
    noticeLine(at: base, "Playing"),
    positionLine(at: base + 2, "playing"),
    positionLine(at: base + 4, playingAt(4_000)),
    positionLine(at: base + 6, ""),
    "",
  ])
  #expect(count == 1)
}

@Test func aSnapshotIsReadAndAFailedOneFallsBackToTheNotice() throws {
  let base = 1_793_000_000.0
  let fields = SnapshotField.allCases.map { field -> String in
    switch field {
    case .persistentID: trackOne
    case .name: "Paper Comet (Live)"
    case .artist: "Velvet Marsh"
    default: ""
    }
  }
  let good = fields.joined(separator: "\\u001f")
  let (count, written) = try replay([
    noticeLine(at: base, "Playing"),
    #"{"at": \#(base + 0.5), "snapshot": "\#(good)"}"#,
    positionLine(at: base + 2, playingAt(2_000)),
    positionLine(at: base + 4, playingAt(4_000)),
    noticeLine(at: base + 5, "Playing", id: trackTwo),
    #"{"at": \#(base + 5.5), "snapshot": "stopped"}"#,
    positionLine(at: base + 7, playingAt(2_000, id: trackTwo)),
    positionLine(at: base + 9, playingAt(4_000, id: trackTwo)),
    #"{"at": \#(base + 10), "quit": true}"#,
  ])
  #expect(count == 2)
  #expect(written.count == 2)
}

@Test(arguments: [
  ("not json", "not a JSON object"),
  ("[1]", "not a JSON object"),
  (#"{"quit": true}"#, "no number at \"at\""),
  (#"{"at": 1793000000.0}"#, "expected one of notice, position, snapshot or quit"),
  (
    #"{"at": 1793000000.0, "quit": true, "position": ""}"#,
    "expected one of notice, position, snapshot or quit"
  ),
  (#"{"at": 1793000000.0, "quit": false}"#, "quit must be true"),
  (#"{"at": 1793000000.0, "position": 5}"#, "position must be text"),
  (#"{"at": 1793000000.0, "snapshot": 5}"#, "snapshot must be text"),
  (#"{"at": 1793000000.0, "notice": 5}"#, "notice must be an object"),
  (
    #"{"at": 1793000000.0, "notice": {"Player State": "Rewinding"}}"#,
    "notice has no known Player State"
  ),
])
func aBadTraceLineIsRefusedWithItsNumber(line: String, reason: String) throws {
  let error = try replayError([noticeLine(at: 1_792_999_999, "Paused"), line])
  #expect(error == .badLine(2, reason))
}

@Test func aMissingTraceIsUnreadable() throws {
  let temp = try TempFolder()
  #expect(throws: ReplayError.unreadable(FileIOError(call: "open", code: ENOENT))) {
    try Replay.run(trace: temp.child("absent.jsonl"), out: temp.child("out"))
  }
}

@Test func aTraceThatIsNotUTF8IsRefused() throws {
  let temp = try TempFolder()
  let file = temp.child("trace.jsonl")
  try Data([0xFF, 0xFE, 0x0A]).write(to: file)
  #expect(throws: ReplayError.badLine(0, "not UTF-8 text")) {
    try Replay.run(trace: file, out: temp.child("out"))
  }
}

@Test func aFailedSnapshotWithNoPlayOpenChangesNothing() throws {
  let (count, written) = try replay([#"{"at": 1793000000.0, "snapshot": ""}"#])
  #expect(count == 0)
  #expect(written.isEmpty)
}

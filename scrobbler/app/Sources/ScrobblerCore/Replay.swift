import Foundation
import os

/// Why a trace could not be replayed.
public enum ReplayError: Error, Equatable, Sendable {
  /// The trace file could not be read.
  case unreadable(FileIOError)
  /// The trace's line `line`, counting from 1, is not an event; 0 is the whole file.
  case badLine(Int, String)
}

/// Feeds a recorded trace to the play engine and writes the listens it would queue.
///
/// A trace is JSON Lines, one event per line, each with its time in Unix seconds as `at`
/// and exactly one of: `notice`, a playerInfo notice's fields; `position` or `snapshot`,
/// the text that script returned; or `quit`, which must be `true`. A blank line is skipped.
/// A notice is taken as already debounced, and each read is handled as the app handles
/// it: an empty position is Music gone, a malformed one is skipped, and a failed snapshot
/// falls back to the notice. Play IDs count up from a fixed start and dates are read in
/// UTC, so the same trace always gives the same bytes. It reads no Music, no config and
/// no network; it writes only into the output folder, one queue file per listen.
public enum Replay {
  /// The largest trace read: far past any hand-made one.
  static let maxTraceBytes = 16 * 1024 * 1024
  /// The keys an event may carry besides `at`.
  static let eventKeys: Set<String> = ["notice", "position", "snapshot", "quit"]

  /// Replay the trace at `trace` into the folder `out`, returning how many listens were
  /// written.
  public static func run(trace: URL, out: URL) throws -> Int {
    let data: Data
    do {
      data = try FileIO.readRegularFile(trace, limit: maxTraceBytes)
    } catch {
      throw ReplayError.unreadable(error)
    }
    guard let text = String(data: data, encoding: .utf8) else {
      throw ReplayError.badLine(0, "not UTF-8 text")
    }
    let queue = QueueStore(queueDir: out, refusedDir: out.appendingPathComponent("refused"))
    var engine = Engine(newPlayID: seededPlayIDs())
    var written = 0
    for (index, line) in text.split(separator: "\n", omittingEmptySubsequences: false)
      .enumerated() where !line.isEmpty
    {
      let input = try event(String(line), number: index + 1, openTrack: engine.openPlay)
      for case .enqueue(let record) in input.map({ engine.handle($0) }) ?? [] {
        try queue.enqueue(record)
        written += 1
      }
    }
    return written
  }

  /// Play IDs counting up from 1, in the contract's lowercase UUID form.
  static func seededPlayIDs() -> @Sendable () -> String {
    let counter = OSAllocatedUnfairLock(initialState: 0)
    return {
      let next = counter.withLock { value -> Int in
        value += 1
        return value
      }
      return String(format: "00000000-0000-4000-8000-%012d", next)
    }
  }

  /// The engine input for trace line `number`, or nil for a read the app skips; the open
  /// play names the track a failed snapshot was of.
  static func event(_ line: String, number: Int, openTrack: OpenPlay?) throws -> EngineInput? {
    // A line that is not JSON at all is refused just as one that is not an object.
    guard let object = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any]
    else { throw ReplayError.badLine(number, "not a JSON object") }
    guard let time = object["at"] as? Double else {
      throw ReplayError.badLine(number, "no number at \"at\"")
    }
    let kinds = eventKeys.intersection(object.keys)
    guard kinds.count == 1, let kind = kinds.first else {
      throw ReplayError.badLine(number, "expected one of notice, position, snapshot or quit")
    }
    do {
      return try input(kind, object[kind], at: time, openTrack: openTrack)
    } catch {
      throw ReplayError.badLine(number, error.reason)
    }
  }

  /// The input an event of `kind` carrying `value` makes at `time`.
  private static func input(_ kind: String, _ value: Any?, at time: Double, openTrack: OpenPlay?)
    throws(BadEvent) -> EngineInput?
  {
    switch kind {
    case "notice":
      guard let fields = value as? [String: Any] else { throw BadEvent("notice must be an object") }
      guard let notice = PlayerNotice.parse(fields) else {
        throw BadEvent("notice has no known Player State")
      }
      return .notice(notice, at: time)
    case "position":
      guard let text = value as? String else { throw BadEvent("position must be text") }
      return positionInput(text, at: time)
    case "snapshot":
      guard let text = value as? String else { throw BadEvent("snapshot must be text") }
      return snapshotInput(text, at: time, openTrack: openTrack)
    default:
      guard value as? Bool == true else { throw BadEvent("quit must be true") }
      return .musicQuit(at: time)
    }
  }

  /// A position read's input: Music gone when empty, and nothing when malformed.
  private static func positionInput(_ text: String, at time: Double) -> EngineInput? {
    switch PositionParser.parse(text) {
    case .success(let read): .position(read, at: time)
    case .failure(.musicNotRunning): .musicQuit(at: time)
    case .failure: nil
    }
  }

  /// A snapshot read's input, its dates read in UTC.
  private static func snapshotInput(_ text: String, at time: Double, openTrack: OpenPlay?)
    -> EngineInput
  {
    switch SnapshotParser.parse(text, timeZone: utc) {
    case .success(let snapshot): .snapshot(snapshot, at: time)
    case .failure(let error):
      .snapshotFailed(persistentID: openTrack?.persistentID ?? "", error, at: time)
    }
  }

  /// The zone every replayed date is read in.
  private static let utc = TimeZone.gmt
}

/// Why one event could not be read, before its line number is known.
private struct BadEvent: Error {
  let reason: String

  init(_ reason: String) {
    self.reason = reason
  }
}

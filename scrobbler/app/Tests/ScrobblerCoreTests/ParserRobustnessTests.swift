import Foundation
import Testing

@testable import ScrobblerCore

/// A fixed-seed generator, so every run feeds the parsers the same inputs and a failure
/// reproduces exactly.
private struct SplitMix64: RandomNumberGenerator {
  var state: UInt64

  mutating func next() -> UInt64 {
    state &+= 0x9E37_79B9_7F4A_7C15
    var mixed = state
    mixed = (mixed ^ (mixed >> 30)) &* 0xBF58_476D_1CE4_E5B9
    mixed = (mixed ^ (mixed >> 27)) &* 0x94D0_49BB_1331_11EB
    return mixed ^ (mixed >> 31)
  }
}

/// The seed every robustness run starts from.
private let robustnessSeed: UInt64 = 0x5C20_B81E_2026_1109
/// How many random inputs each robustness test feeds through.
private let robustnessCases = 10_000

/// Pieces a random result line is built from: the separator, numbers at and past the
/// integer limits, the boolean words, hex, and text the parsers must not choke on.
private let fragments: [String] = [
  String(MusicScripts.separator), String(MusicScripts.separator), "", "0", "1", "-1", "+7",
  "214000", "9223372036854775807", "9223372036854775808", "-9223372036854775809", "1.5",
  "1e3", "true", "false", "TRUE", "missing value", "playing", "paused", "stopped",
  "rewinding", "0a1b2c3d4e5f6071", "FFFFFFFFFFFFFFFF", "0A1B2C3D4E5F607100", "\u{FF10}",
  "\u{0301}", "e\u{0301}", "\r\n", "\n", " ", "\u{0}", "\u{1E}", "\u{FEFF}", "Harbor", "\u{1F600}",
  // Date parts: well formed, at the year limits, overflowing, and broken by a stray slash.
  "2024/1/15/43200", "1/1/1/0", "9999/12/31/86399", "9223372036854775807/1/1/0",
  "2024/2/30/0", "/",
]

/// One random line: either free-form fragments, or exactly a parser's field count so the
/// per-field checks run rather than the count check alone.
private func randomLine(fieldCount: Int, using rng: inout SplitMix64) -> String {
  if Bool.random(using: &rng) {
    let length = Int.random(in: 0...12, using: &rng)
    return (0..<length).map { _ in fragments.randomElement(using: &rng) ?? "" }.joined()
  }
  let pieces = fragments.filter { $0 != String(MusicScripts.separator) }
  return (0..<fieldCount).map { _ in pieces.randomElement(using: &rng) ?? "" }
    .joined(separator: String(MusicScripts.separator))
}

/// A random value of the kinds a notice's userInfo could hold.
private func randomValue(using rng: inout SplitMix64) -> Any {
  switch Int.random(in: 0..<8, using: &rng) {
  case 0: return fragments.randomElement(using: &rng) ?? ""
  case 1: return Int.random(in: Int.min...Int.max, using: &rng)
  case 2: return Double.random(in: -1e20...1e20, using: &rng)
  case 3: return [Double.nan, .infinity, -.infinity, 1e300].randomElement(using: &rng) ?? 0
  case 4: return Bool.random(using: &rng)
  case 5: return NSNumber(value: UInt64.random(in: 0...UInt64.max, using: &rng))
  case 6: return NSNull()
  default: return ["0A1B"]
  }
}

private let noticeKeys = [
  "Player State", "Persistent ID", "Name", "Artist", "Album", "Total Time", "Location",
]

@Test func snapshotParserNeverTrapsOnRandomText() {
  var rng = SplitMix64(state: robustnessSeed)
  for _ in 0..<robustnessCases {
    let line = randomLine(fieldCount: SnapshotField.allCases.count, using: &rng)
    if case .success = SnapshotParser.parse(line) {
      #expect(
        line.split(separator: MusicScripts.separator, omittingEmptySubsequences: false).count
          == SnapshotField.allCases.count)
    }
  }
}

@Test func positionParserNeverTrapsOnRandomText() {
  var rng = SplitMix64(state: robustnessSeed)
  for _ in 0..<robustnessCases {
    let line = randomLine(fieldCount: 4, using: &rng)
    if case .success(let read) = PositionParser.parse(line) {
      #expect(read.positionMs >= 0)
      #expect(read.persistentID == nil || read.persistentID?.count == 16)
    }
  }
}

@Test func noticeParserNeverTrapsOnRandomDictionaries() {
  var rng = SplitMix64(state: robustnessSeed)
  for _ in 0..<robustnessCases {
    var info: [AnyHashable: Any] = [:]
    for key in noticeKeys where Bool.random(using: &rng) {
      info[key] = randomValue(using: &rng)
    }
    if Bool.random(using: &rng) {
      info["Player State"] = ["Playing", "Paused", "Stopped"].randomElement(using: &rng)
    }
    if let notice = PlayerNotice.parse(info) {
      #expect(notice.persistentID == nil || notice.persistentID?.count == 16)
      #expect((notice.totalTimeMs ?? 0) >= 0)
    }
  }
}

@Test func persistentIDNeverTrapsOnRandomValues() {
  var rng = SplitMix64(state: robustnessSeed)
  for _ in 0..<robustnessCases {
    let normalized = PersistentID.normalize(randomValue(using: &rng))
    #expect(normalized == nil || normalized?.count == 16)
  }
}

@Test func splitMixMatchesItsPublishedFirstOutput() {
  // SplitMix64 seeded with 0 yields this value first, so the generator is the real one.
  var rng = SplitMix64(state: 0)
  #expect(rng.next() == 0xE220_A839_7B1D_CDAF)
}

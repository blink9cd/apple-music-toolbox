import Foundation
import Testing

@testable import ScrobblerCore

/// What the snapshot script's `escapedText` writes for each character it escapes: a
/// percent sign and the character's two uppercase hex digits.
private let escapedScalars: [Unicode.Scalar: String] = [
  "%": "%25", "\u{1F}": "%1F", "\t": "%09", "\n": "%0A", "\r": "%0D",
]

/// `text` with each character the snapshot escapes replaced by its escape, scalar by
/// scalar: a reference the parser must undo.
///
/// Not a model of the AppleScript handler, which leaves a percent sign fused with a
/// following combining mark as it is; the parser reads either form the same. What the
/// handler really writes is shown by running it: tag_refresh's
/// `test_script_text_osascript.py` runs this script's copy through `osascript`.
private func escapedForScript(_ text: String) -> String {
  text.unicodeScalars.map { escapedScalars[$0] ?? String($0) }.joined()
}

/// One snapshot result as the script writes it: every text field escaped, the rest kept.
private func escapedLine(_ values: [SnapshotField: String]) -> String {
  SnapshotField.allCases.map { field in
    let value = values[field] ?? ""
    return field.kind == .text ? escapedForScript(value) : value
  }
  .joined(separator: String(MusicScripts.separator))
}

/// Every character the script escapes, the pair Windows text ends lines with, an escape's
/// own text left as plain text, and a sign followed by an unknown code.
private let awkward = ["\t", "\n", "\r", "\r\n", "\u{1F}", "%", "%09", "%25", "%41", "100%"]

/// The snapshot's text fields, each paired with the property it reads into.
private func textFields() -> [(SnapshotField, KeyPath<TrackSnapshot, String?>)] {
  [
    (.trackClass, \.trackClass), (.location, \.location), (.name, \.name),
    (.artist, \.artist), (.album, \.album), (.albumArtist, \.albumArtist),
    (.composer, \.composer), (.genre, \.genre), (.grouping, \.grouping), (.work, \.work),
    (.movement, \.movement), (.kind, \.kind), (.mediaKind, \.mediaKind),
    (.musicVersion, \.musicVersion),
  ]
}

@Test func everyTextFieldIsListedOnce() {
  let text = SnapshotField.allCases.filter { $0.kind == .text }
  #expect(textFields().map(\.0) == text)
}

@Test func eachAwkwardCharacterReadsBackInEachTextField() throws {
  for (field, property) in textFields() {
    for character in awkward {
      let value = "Invented\(character)Value"
      let snap = try SnapshotParser.parse(escapedLine([field: value])).get()
      #expect(snap[keyPath: property] == value, "\(field) \(character.debugDescription)")
    }
  }
}

@Test func everyEscapeIsUndone() {
  #expect(FieldText.unescaped("a%25b%1Fc%09d%0Ae%0Df%0D%0Ag") == "a%b\u{1F}c\td\ne\rf\r\ng")
}

@Test func aSignThatBeginsNoEscapeIsKept() {
  for text in ["100% Invented", "%", "Invented %", "%G0", "%0", "%1f", "%\u{301}09"] {
    #expect(FieldText.unescaped(Substring(text)) == text, "\(text.debugDescription)")
  }
}

@Test func anEscapedSignIsNotReadAgain() {
  #expect(FieldText.unescaped("%2509") == "%09")
}

@Test func aPieceDecodingPastTheCapIsDroppedAndOneAtItKept() throws {
  // An escape is three bytes for one, so a piece over three times the cap cannot decode
  // to a value within it; the parser drops it before decoding.
  let atCap = String(repeating: "%", count: FieldText.maxTextBytes)
  let kept = try SnapshotParser.parse(escapedLine([.name: atCap])).get()
  #expect(kept.name == atCap)
  let over = try SnapshotParser.parse(escapedLine([.name: atCap + "a"])).get()
  #expect(over.name == nil)
}

/// Scalars a random text field is built from: every escaped one, the escape's own
/// digits, a combining mark, and a few ordinary and wide characters.
private let textScalars: [Unicode.Scalar] = [
  "%", "\u{1F}", "\t", "\n", "\r", "0", "1", "2", "5", "9", "A", "D", "F", "a", " ",
  "\u{301}", "\u{E9}", "\u{FEFF}", "\u{1F600}",
]

@Test func anyTextReadsBackThroughTheEscape() {
  var rng = SplitMix64(state: 0x41_2026_1111)
  for _ in 0..<10_000 {
    let length = Int.random(in: 0...16, using: &rng)
    var view = String.UnicodeScalarView()
    for _ in 0..<length { view.append(textScalars.randomElement(using: &rng) ?? "%") }
    let text = String(view)
    #expect(FieldText.unescaped(Substring(escapedForScript(text))) == text)
    let snap = try? SnapshotParser.parse(escapedLine([.name: text])).get()
    #expect(snap?.name == (text.isEmpty ? nil : text))
  }
}

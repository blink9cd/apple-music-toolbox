import Foundation
import Testing

@testable import ScrobblerCore

/// A temp folder holding a token file named `token`, written with `text` and `mode`.
private func tokenFile(_ text: String, mode: Int = 0o600) throws -> (TempFolder, URL) {
  let temp = try TempFolder()
  let url = temp.child("token")
  try writeFile(text, to: url, mode: mode)
  return (temp, url)
}

@Test func theTestTokenHasTheTokenShape() {
  #expect(testToken.count == 64)
}

@Test func readsAGoodTokenWithItsNewline() throws {
  let (temp, url) = try tokenFile(testToken + "\n")
  #expect(try TokenReader.read(at: url, uid: getuid()) == testToken)
  _ = temp
}

@Test func readsAGoodTokenWithoutANewline() throws {
  let (temp, url) = try tokenFile(testToken)
  #expect(try TokenReader.read(at: url, uid: getuid()) == testToken)
  _ = temp
}

@Test func anAbsentFileIsMissing() throws {
  let temp = try TempFolder()
  #expect(throws: TokenError.missing) {
    try TokenReader.read(at: temp.child("token"), uid: getuid())
  }
}

@Test func aSymlinkToAGoodTokenIsRefused() throws {
  let (temp, target) = try tokenFile(testToken)
  let link = temp.child("link")
  try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
  #expect(throws: TokenError.notRegularFile) {
    try TokenReader.read(at: link, uid: getuid())
  }
}

@Test func aDirectoryIsNotARegularFile() throws {
  let temp = try TempFolder()
  let folder = temp.child("token")
  try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
  try setMode(0o700, of: folder)
  #expect(throws: TokenError.notRegularFile) {
    try TokenReader.read(at: folder, uid: getuid())
  }
}

@Test func aFileOthersCanReadIsTooOpen() throws {
  let (temp, url) = try tokenFile(testToken, mode: 0o644)
  #expect(throws: TokenError.tooOpen) { try TokenReader.read(at: url, uid: getuid()) }
  _ = temp
}

@Test func aFileAnotherUserHoldsIsWrongOwner() throws {
  let (temp, url) = try tokenFile(testToken)
  #expect(throws: TokenError.wrongOwner) { try TokenReader.read(at: url, uid: getuid() + 1) }
  _ = temp
}

@Test func aFileOverTheCapIsTooLarge() throws {
  let (temp, url) = try tokenFile(String(repeating: "a", count: 5000))
  #expect(throws: TokenError.tooLarge) { try TokenReader.read(at: url, uid: getuid()) }
  _ = temp
}

@Test func aFileAtTheCapIsReadAndJudgedByItsContent() throws {
  let (temp, url) = try tokenFile(String(repeating: "a", count: TokenReader.maxFileBytes))
  #expect(throws: TokenError.malformed) { try TokenReader.read(at: url, uid: getuid()) }
  _ = temp
}

@Test(arguments: [
  String(testToken.dropLast()), testToken.uppercased(), testToken + "\n\n", "",
  testToken + " ", "\n" + testToken, String(testToken.dropLast()) + "g",
])
func aFileWithoutExactlyOneTokenIsMalformed(text: String) throws {
  let (temp, url) = try tokenFile(text)
  #expect(throws: TokenError.malformed) { try TokenReader.read(at: url, uid: getuid()) }
  _ = temp
}

@Test func aFileThatCannotBeOpenedIsUnreadable() throws {
  let (temp, url) = try tokenFile(testToken, mode: 0o000)
  #expect(throws: TokenError.unreadable) { try TokenReader.read(at: url, uid: getuid()) }
  _ = temp
}

@Test func noErrorDescriptionCarriesTheToken() {
  let cases: [TokenError] = [
    .missing, .notRegularFile, .wrongOwner, .tooOpen, .tooLarge, .malformed, .unreadable,
  ]
  for error in cases {
    #expect(!String(describing: error).contains(testToken))
    #expect(!(error as NSError).localizedDescription.contains(testToken))
  }
}

/// Never-crash and exactness over generated inputs: `tokenText` accepts a byte string only
/// when it is 64 lowercase hex digits plus at most one newline, and then returns those digits.
@Test func tokenTextAcceptsExactlyTheTokenShape() {
  var generator = SystemRandomNumberGenerator()
  let alphabet = Array("0123456789abcdefABCDEFg\n \u{0}".utf8)
  for _ in 0..<2000 {
    let length = Int.random(in: 0...70, using: &generator)
    let bytes = (0..<length).map { _ in alphabet.randomElement(using: &generator) ?? 0 }
    let body = bytes.last == UInt8(ascii: "\n") ? bytes.dropLast() : bytes[...]
    let lowerHex = Set("0123456789abcdef".utf8)
    let valid = body.count == 64 && body.allSatisfy(lowerHex.contains)
    let token = TokenReader.tokenText(Data(bytes))
    #expect((token != nil) == valid)
    if let token { #expect(Data(token.utf8) == Data(body)) }
  }
}

@Test func noRefusalWordingCarriesTheToken() throws {
  let temp = try TempFolder()
  let uid = getuid()
  var refusals: [TokenError] = []
  func refusal(_ text: String, mode: Int = 0o600, uid readAs: uid_t = uid) throws {
    let url = temp.child("token-\(refusals.count)")
    try writeFile(text, to: url, mode: mode)
    refusals.append(
      try #require(throws: TokenError.self) { try TokenReader.read(at: url, uid: readAs) })
  }
  try refusal(testToken, mode: 0o644)
  try refusal(testToken, uid: uid + 1)
  try refusal(String(repeating: testToken, count: 70))
  try refusal(testToken + "\n\n")
  try refusal(testToken.uppercased())
  let link = temp.child("link")
  try FileManager.default.createSymbolicLink(at: link, withDestinationURL: temp.child("token-0"))
  refusals.append(
    try #require(throws: TokenError.self) { try TokenReader.read(at: link, uid: uid) })
  #expect(refusals == [.tooOpen, .wrongOwner, .tooLarge, .malformed, .malformed, .notRegularFile])
  for error in refusals {
    let wording = "token unreadable: \(error)"
    #expect(!wording.lowercased().contains(testToken.prefix(8)))
  }
}

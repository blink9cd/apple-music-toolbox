import Testing

@testable import ScrobblerCore

/// How a Music script's error numbers and answers become the reads' results.
@Suite struct AppleScriptErrorTests {
  @Test func aRefusedAutomationIsDenied() {
    #expect(SnapshotReadError.fromAppleScriptError(number: -1743) == .automationDenied)
  }

  @Test func aTrackThatVanishedMidReadIsNoCurrentTrack() {
    #expect(SnapshotReadError.fromAppleScriptError(number: -1728) == .noCurrentTrack)
  }

  @Test(arguments: [-600, -609])
  func musicQuittingMidReadIsNotRunning(number: Int) {
    #expect(SnapshotReadError.fromAppleScriptError(number: number) == .musicNotRunning)
  }

  @Test func anyOtherNumberIsMalformedAndNamed() {
    #expect(
      SnapshotReadError.fromAppleScriptError(number: -2753) == .malformed("AppleScript error -2753")
    )
  }

  @Test func aMissingNumberIsMalformed() {
    #expect(
      SnapshotReadError.fromAppleScriptError(number: nil)
        == .malformed("AppleScript error without a number"))
  }

  @Test func returnedTextGoesToTheParserUntouched() {
    let answer = ScriptAnswer.returned(" stopped\n")
    let result = answer.parsed { text -> Result<String, SnapshotReadError> in .success(text) }
    #expect(result == .success(" stopped\n"))
  }

  @Test func aResultThatIsNotTextIsMalformed() {
    let result = ScriptAnswer.returned(nil).parsed(by: PositionParser.parse)
    #expect(result == .failure(.malformed("the script's result is not text")))
  }

  @Test func aRaisedErrorIsMappedWithoutParsing() {
    let result = ScriptAnswer.raised(number: -1743).parsed(by: PositionParser.parse)
    #expect(result == .failure(.automationDenied))
  }

  @Test func musicIsKnownByItsBundleIDAlone() {
    #expect(MusicApp.isMusic(bundleIdentifier: "com.apple.Music"))
    #expect(!MusicApp.isMusic(bundleIdentifier: "com.apple.music"))
    #expect(!MusicApp.isMusic(bundleIdentifier: "com.apple.Safari"))
    #expect(!MusicApp.isMusic(bundleIdentifier: nil))
    #expect(MusicApp.playerInfoNotice == "com.apple.Music.playerInfo")
  }
}

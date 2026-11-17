import Foundation
import Testing

@testable import ScrobblerCore

/// Both reads compile as AppleScript, whole.
///
/// The text pins in `MusicScriptsTests` compare the scripts against an expected copy, so
/// a syntax error written into both passes them; the escape handler's own run under
/// `osascript` (tag_refresh's `test_script_text_osascript.py`) compiles only that handler.
/// This compiles every script as the live layer will, so a block the language does not
/// accept fails here rather than first in the live smoke test.
///
/// Compiling reads Music's dictionary from the app bundle and sends no Apple event: it
/// neither launches Music nor reads the library, so it stays inside the unit tests'
/// no-live-host rule. `NSAppleScript` is used from the main actor, as its documentation
/// asks.
@MainActor
@Suite struct ScriptCompileTests {
  /// The compile error's number and message for *source*, or nil when it compiled.
  private static func compileError(_ source: String) -> String? {
    // `NSAppleScript(source:)` is nil only for a nil source, which a `String` never is.
    guard let script = NSAppleScript(source: source) else { return "no script" }
    var error: NSDictionary?
    if script.compileAndReturnError(&error) { return nil }
    let number = error?[NSAppleScript.errorNumber] ?? "?"
    let message = error?[NSAppleScript.errorMessage] ?? "?"
    return "\(number): \(message)"
  }

  @Test func theSnapshotReadCompiles() {
    let error = Self.compileError(MusicScripts.snapshotSource())
    #expect(error == nil, "\(error ?? "")")
  }

  @Test func thePositionReadCompiles() {
    let error = Self.compileError(MusicScripts.positionSource)
    #expect(error == nil, "\(error ?? "")")
  }

  @Test func aScriptWithASyntaxErrorDoesNot() {
    // The probe itself can fail: the ending this suite was written to catch.
    let broken = "with timeout of 5 seconds\n  return 1\nend with timeout\n"
    #expect(Self.compileError(broken) != nil)
  }
}

import Foundation
import Testing

@testable import ScrobblerCore

/// A log at `url` holding `text`, opened for appending as launchd opens an agent's log.
func openLog(_ url: URL, holding text: String, flags: Int32 = O_WRONLY | O_APPEND) throws
  -> Int32
{
  try writeFile(text, to: url)
  let descriptor = open(url.path, flags | O_CLOEXEC)
  #expect(descriptor >= 0)
  return descriptor
}

/// The text of the file at `url`.
func logText(_ url: URL) throws -> String {
  try #require(String(bytes: try Data(contentsOf: url), encoding: .utf8))
}

@Test func aLogAtOrUnderTheLimitIsLeftAlone() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "one\ntwo\n")
  defer { close(descriptor) }
  #expect(!LogCap.trim(descriptor: descriptor, path: url, limit: 8, kept: 4))
  #expect(try logText(url) == "one\ntwo\n")
}

@Test func aLogOverTheLimitKeepsItsLastWholeLines() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "first line\nsecond\nthird\n")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 16, kept: 10))
  #expect(try logText(url) == "third\n")
  // The next write lands right after what was kept, never past a hole at the old end.
  _ = "next\n".withCString { write(descriptor, $0, 5) }
  #expect(try logText(url) == "third\nnext\n")
}

@Test func aWindowStartingAtALineBreakKeepsItsFirstWholeLine() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  // The six bytes kept start right after a line break, so "bb" is a whole line.
  let descriptor = try openLog(url, holding: "aaaa\nbb\ncc\n")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 6))
  #expect(try logText(url) == "bb\ncc\n")
}

@Test func aWindowStartingMidLineDropsThePartLine() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  // The six bytes kept start inside "bbbb", so its tail "bb" is dropped.
  let descriptor = try openLog(url, holding: "aaaa\nbbbb\ncc\n")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 6))
  #expect(try logText(url) == "cc\n")
}

@Test func aWindowAsLongAsTheLogKeepsItWhole() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  // A window holding the whole file starts at the file's start, which starts a line.
  let descriptor = try openLog(url, holding: "ab\ncd\n")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 2, kept: 64))
  #expect(try logText(url) == "ab\ncd\n")
}

@Test(arguments: [-1, 0, 3])
func aFailedOrShortReadLeavesTheLogUntouched(got: Int) throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "0123456789\nabcdef\n")
  defer { close(descriptor) }
  let read: LogCap.PositionalRead = { _, _, _, _ in got }
  #expect(!LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 8, read: read))
  #expect(try logText(url) == "0123456789\nabcdef\n")
}

@Test func aTailWithNoLineBreakIsKeptWhole() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "abcdefghijklmnop")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 8, kept: 4))
  #expect(try logText(url) == "mnop")
}

@Test func aTailWhoseOnlyLineBreakEndsItIsKeptWhole() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "abcdefgh\n")
  defer { close(descriptor) }
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 4))
  #expect(try logText(url) == "fgh\n")
}

@Test func aDescriptorOpenedWithoutAppendIsRewoundBeforeTheTailIsWritten() throws {
  let temp = try TempFolder()
  let url = temp.child("out.log")
  let descriptor = try openLog(url, holding: "0123456789\nabc\n", flags: O_WRONLY)
  defer { close(descriptor) }
  lseek(descriptor, 0, SEEK_END)
  #expect(LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 6))
  #expect(try logText(url) == "abc\n")
}

@Test func aDescriptorThatIsNotThePathsFileIsLeftAlone() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let other = temp.child("mine.log")
  try writeFile("the agent's log\n", to: url)
  let descriptor = try openLog(other, holding: "a long file a person redirected\n")
  defer { close(descriptor) }
  #expect(!LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 4))
  #expect(try logText(other) == "a long file a person redirected\n")
}

@Test func aMissingOrLinkedPathLeavesTheLogAlone() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "0123456789\n")
  defer { close(descriptor) }
  #expect(!LogCap.trim(descriptor: descriptor, path: temp.child("absent.log"), limit: 4, kept: 4))
  let link = temp.child("link.log")
  try FileManager.default.createSymbolicLink(at: link, withDestinationURL: url)
  #expect(!LogCap.trim(descriptor: descriptor, path: link, limit: 4, kept: 4))
  #expect(try logText(url) == "0123456789\n")
}

@Test func aDescriptorThatIsNotARegularFileIsLeftAlone() throws {
  var ends: [Int32] = [0, 0]
  #expect(pipe(&ends) == 0)
  defer { for end in ends { close(end) } }
  #expect(!LogCap.trim(descriptor: ends[1], path: URL(fileURLWithPath: "/dev/null")))
}

@Test func aLogThatCannotBeTruncatedIsLeftAlone() throws {
  let temp = try TempFolder()
  let url = temp.child("err.log")
  let descriptor = try openLog(url, holding: "0123456789\n", flags: O_RDONLY)
  defer { close(descriptor) }
  #expect(!LogCap.trim(descriptor: descriptor, path: url, limit: 4, kept: 4))
  #expect(try logText(url) == "0123456789\n")
}

@Test func theDefaultsBoundTheLogToAboutAMebibyte() {
  #expect(LogCap.limit == 1 << 20)
  #expect(LogCap.kept < LogCap.limit)
}

@Test func aRefusalEndsTheAppWithoutARestartAndARetryWithOne() {
  // The launch agent's plist restarts the app only after a failed exit (SuccessfulExit
  // false), so a refusal must exit 0 and a retry must not.
  #expect(RunExit.refused == EXIT_SUCCESS)
  #expect(RunExit.retry != EXIT_SUCCESS)
}

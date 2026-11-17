import Foundation
import Testing

@testable import ScrobblerCore

/// The folders the app makes for itself: private, and never reached through a link.
@Suite struct PrivateFolderTests {
  /// The permission bits of the entry at `url`, not following a link.
  func mode(of url: URL) -> Int {
    var info = stat()
    #expect(lstat(url.path, &info) == 0)
    return Int(info.st_mode & 0o7777)
  }

  /// A real folder at `target`, private, and a link to it at `link`, whose parent is made.
  func linkFolder(_ link: URL, to target: URL) throws {
    let manager = FileManager.default
    try manager.createDirectory(at: target, withIntermediateDirectories: true)
    try setMode(0o700, of: target)
    try manager.createDirectory(
      at: link.deletingLastPathComponent(), withIntermediateDirectories: true)
    try manager.createSymbolicLink(at: link, withDestinationURL: target)
  }

  @Test func everyMissingLevelAboveTheDataFolderIsMadePrivate() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    try paths.makeDataFolders()
    var level = paths.dataDir
    while level.path != temp.url.path {
      #expect(mode(of: level) == 0o700, "\(level.lastPathComponent)")
      level = level.deletingLastPathComponent()
    }
  }

  @Test func aLevelThatAlreadyExistsAboveTheNewOnesIsLeftAsItIs() throws {
    let temp = try TempFolder()
    let library = temp.child("Library")
    try FileManager.default.createDirectory(at: library, withIntermediateDirectories: false)
    try setMode(0o755, of: library)
    try ScrobblerPaths(home: temp.url).makeDataFolders()
    #expect(mode(of: library) == 0o755)
  }

  @Test func anExistingLinkAboveTheDataFolderIsFollowedAsFound() throws {
    // The levels above the data folder are the user's own, so one the user made a link
    // (Application Support moved to another disk, say) is used as found.
    let temp = try TempFolder()
    let moved = temp.child("moved")
    try linkFolder(temp.child("Library/Application Support"), to: moved)
    let paths = ScrobblerPaths(home: temp.url)
    try paths.makeDataFolders()
    let made = try names(in: moved.appendingPathComponent("listensmith/scrobbler"))
    #expect(made == ["logs", "queue", "refused", "state"])
  }

  @Test func aLinkAtTheDataFolderIsRefusedAndNothingIsMadeThroughIt() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    let elsewhere = temp.child("elsewhere")
    try linkFolder(paths.dataDir, to: elsewhere)
    #expect(throws: FileIOError.self) { try paths.makeDataFolders() }
    #expect(try names(in: elsewhere).isEmpty)
  }

  @Test(arguments: ["queue", "refused", "state", "logs"])
  func aLinkAtAFolderTheAppMakesIsRefused(name: String) throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    let elsewhere = temp.child("elsewhere")
    try linkFolder(paths.dataDir.appendingPathComponent(name), to: elsewhere)
    #expect(throws: FileIOError.self) { try paths.makeDataFolders() }
    #expect(try names(in: elsewhere).isEmpty)
  }

  @Test func aLinkAtTheLockFolderIsUnopenableAndNoLockIsMadeThroughIt() throws {
    let temp = try TempFolder()
    let elsewhere = temp.child("elsewhere")
    try linkFolder(temp.child("state"), to: elsewhere)
    let lock = temp.child("state/scrobbler.lock")
    #expect(InstanceLock.acquire(at: lock, owning: temp.url).isUnopenable)
    #expect(try names(in: elsewhere).isEmpty)
  }

  @Test func aLinkAtTheDataFolderMakesTheLockUnopenableAndNothingIsMadeThroughIt() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    let elsewhere = temp.child("elsewhere")
    try linkFolder(paths.dataDir, to: elsewhere)
    #expect(InstanceLock.acquire(at: paths.lockFile, owning: paths.dataDir).isUnopenable)
    #expect(try names(in: elsewhere).isEmpty)
  }

  @Test func aLinkAtTheDataFolderIsUnopenableWhenItsTargetHoldsAStateFolder() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    let elsewhere = temp.child("elsewhere")
    try linkFolder(paths.dataDir, to: elsewhere)
    let state = elsewhere.appendingPathComponent("state")
    try FileManager.default.createDirectory(at: state, withIntermediateDirectories: false)
    try setMode(0o700, of: state)
    #expect(InstanceLock.acquire(at: paths.lockFile, owning: paths.dataDir).isUnopenable)
    #expect(try names(in: state).isEmpty)
  }

  @Test func aLinkAtAFolderARecordIsWrittenInIsRefused() throws {
    let temp = try TempFolder()
    let elsewhere = temp.child("elsewhere")
    try linkFolder(temp.child("state"), to: elsewhere)
    #expect(throws: FileIOError.self) {
      try FileIO.writeAtomically(Data("{}".utf8), to: temp.child("state/status.json"))
    }
    #expect(try names(in: elsewhere).isEmpty)
  }

  @Test func aFolderOutsideTheOneItIsMadeUnderIsRefused() throws {
    let temp = try TempFolder()
    #expect(throws: FileIOError(call: "folder path", code: EINVAL)) {
      try FileIO.makeFolder(temp.child("a"), owning: temp.child("b"))
    }
    #expect(try names(in: temp.url).isEmpty)
  }

  @Test func aFolderPathClimbingWithDotDotIsRefused() throws {
    let temp = try TempFolder()
    let climbing = temp.url.appendingPathComponent("a/../b")
    #expect(throws: FileIOError(call: "folder path", code: EINVAL)) {
      try FileIO.makeFolder(climbing, owning: temp.url)
    }
    #expect(try names(in: temp.url).isEmpty)
  }

  @Test func theRootFolderCannotBeTheOneMadeUnder() {
    // Refused before anything is made, so the folder named under the root is never made.
    let folder = URL(fileURLWithPath: "/scrobbler-test")
    #expect(throws: FileIOError(call: "folder path", code: EINVAL)) {
      try FileIO.makeFolder(folder, owning: URL(fileURLWithPath: "/"))
    }
  }

  @Test func aFolderWhoseParentCannotBeMadeIsAnError() throws {
    let temp = try TempFolder()
    try writeFile("in the way", to: temp.child("Library"))
    #expect(throws: FileIOError.self) { try ScrobblerPaths(home: temp.url).makeDataFolders() }
  }

  @Test func aFolderThatCannotBeMadeInItsParentIsAnError() throws {
    let temp = try TempFolder()
    let library = temp.child("Library")
    try FileManager.default.createDirectory(at: library, withIntermediateDirectories: false)
    try setMode(0o500, of: library)
    // Restored before the temp folder is removed, which needs to empty it.
    defer { try? setMode(0o700, of: library) }
    #expect(throws: FileIOError.self) { try ScrobblerPaths(home: temp.url).makeDataFolders() }
  }
}

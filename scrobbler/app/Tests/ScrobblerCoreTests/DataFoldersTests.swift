import Foundation
import Testing

@testable import ScrobblerCore

/// The folders the app writes in, made private before it starts.
@Suite struct DataFoldersTests {
  /// The permission bits of the folder at `url`.
  func mode(of url: URL) throws -> Int {
    let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
    return try #require(attributes[.posixPermissions] as? Int)
  }

  @Test func everyDataFolderIsMadePrivate() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    try paths.makeDataFolders()
    for folder in [paths.dataDir, paths.queueDir, paths.refusedDir, paths.stateDir, paths.logsDir] {
      #expect(try mode(of: folder) == 0o700)
    }
  }

  @Test func makingThemAgainLeavesThemInPlace() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    try paths.makeDataFolders()
    try writeFile("kept", to: paths.queueDir.appendingPathComponent("a.json"))
    try paths.makeDataFolders()
    #expect(try names(in: paths.queueDir) == ["a.json"])
  }

  @Test func aFileWhereAFolderGoesIsAnError() throws {
    let temp = try TempFolder()
    let paths = ScrobblerPaths(home: temp.url)
    try FileManager.default.createDirectory(at: paths.dataDir, withIntermediateDirectories: true)
    try writeFile("in the way", to: paths.stateDir)
    #expect(throws: (any Error).self) { try paths.makeDataFolders() }
  }
}

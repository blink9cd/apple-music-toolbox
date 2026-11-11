import Foundation
import Testing

@testable import ScrobblerCore

@Test func swiftConstantsMatchLayoutFile() throws {
  let here = URL(fileURLWithPath: #filePath)
  let layoutURL = here.deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("layout.json")
  let json =
    try JSONSerialization.jsonObject(with: Data(contentsOf: layoutURL)) as? [String: String]
  let layout = try #require(json)
  #expect(layout.count == 12)
  #expect(layout["version"] == Layout.version)
  #expect(layout["submission_client"] == Layout.submissionClient)
  #expect(layout["bundle_id"] == Layout.bundleID)
  #expect(layout["launchd_label"] == Layout.launchdLabel)
  #expect(layout["display_name"] == Layout.displayName)
  #expect(layout["app_name"] == Layout.appName)
  #expect(layout["executable"] == Layout.executable)
  #expect(layout["data_dir"] == Layout.dataDir)
  #expect(layout["config_file"] == Layout.configFile)
  #expect(layout["token_file"] == Layout.tokenFile)
  #expect(layout["signing_config"] == Layout.signingConfig)
  #expect(layout["launch_agents_dir"] == Layout.launchAgentsDir)
}

@Test func pathsStayUnderTheGivenHome() {
  let home = URL(fileURLWithPath: "/home-for-test", isDirectory: true)
  let paths = ScrobblerPaths(home: home)
  #expect(
    paths.queueDir.path == "/home-for-test/Library/Application Support/listensmith/scrobbler/queue")
  #expect(paths.tokenFile.path == "/home-for-test/.config/listensmith/token")
}

@Test func everyPathSitsWhereTheLayoutSays() {
  let home = URL(fileURLWithPath: "/home-for-test", isDirectory: true)
  let paths = ScrobblerPaths(home: home)
  let data = "/home-for-test/Library/Application Support/listensmith/scrobbler"
  #expect(paths.dataDir.path == data)
  #expect(paths.refusedDir.path == "\(data)/refused")
  #expect(paths.stateDir.path == "\(data)/state")
  #expect(paths.statusFile.path == "\(data)/state/status.json")
  #expect(paths.openPlayFile.path == "\(data)/state/open_play.json")
  #expect(paths.lockFile.path == "\(data)/state/scrobbler.lock")
  #expect(paths.logsDir.path == "\(data)/logs")
  #expect(paths.outLog.path == "\(data)/logs/out.log")
  #expect(paths.errLog.path == "\(data)/logs/err.log")
  #expect(paths.appBundle.path == "\(data)/listensmith scrobbler.app")
  #expect(paths.configFile.path == "/home-for-test/.config/listensmith/scrobbler.json")
  #expect(paths.signingConfig.path == "/home-for-test/.config/swift_gate/signing.toml")
  #expect(paths.launchAgentsDir.path == "/home-for-test/Library/LaunchAgents")
  #expect(
    paths.launchAgentPlist.path
      == "/home-for-test/Library/LaunchAgents/local.listensmith.scrobbler.plist")
}

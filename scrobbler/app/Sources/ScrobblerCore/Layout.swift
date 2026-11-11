import Foundation

/// The scrobbler's names, version and home-relative paths.
///
/// Each constant restates one key of `layout.json`, the file the Python half reads at
/// runtime; `LayoutTests` fails when the two disagree, so the file stays the one source.
public enum Layout {
  /// The scrobbler's version, the `version` key.
  public static let version = "0.1.0"
  /// The `submission_client` every record names, the `submission_client` key.
  public static let submissionClient = "scrobbler"
  /// The app's bundle identifier and log subsystem, the `bundle_id` key.
  public static let bundleID = "local.listensmith.scrobbler"
  /// The launch agent's label, the `launchd_label` key.
  public static let launchdLabel = "local.listensmith.scrobbler"
  /// The name the app shows, the `display_name` key.
  public static let displayName = "listensmith scrobbler"
  /// The app bundle's folder name, the `app_name` key.
  public static let appName = "listensmith scrobbler.app"
  /// The executable's file name, the `executable` key.
  public static let executable = "scrobbler"
  /// The data folder, relative to the home folder, the `data_dir` key.
  public static let dataDir = "Library/Application Support/listensmith/scrobbler"
  /// The config file, relative to the home folder, the `config_file` key.
  public static let configFile = ".config/listensmith/scrobbler.json"
  /// The store's token file, relative to the home folder, the `token_file` key.
  public static let tokenFile = ".config/listensmith/token"
  /// The signing setting, relative to the home folder, the `signing_config` key.
  public static let signingConfig = ".config/swift_gate/signing.toml"
  /// The LaunchAgents folder, relative to the home folder, the `launch_agents_dir` key.
  public static let launchAgentsDir = "Library/LaunchAgents"
}

/// Every file and folder the scrobbler reads or writes, derived under one home folder.
///
/// The home is always given, never looked up here, so a test passes a folder of its own
/// and nothing reaches the real one.
public struct ScrobblerPaths: Equatable, Sendable {
  /// The data folder: the queue, the refused records, the state, the logs and the app.
  public let dataDir: URL
  /// Records waiting to be sent.
  public let queueDir: URL
  /// Records the store refused.
  public let refusedDir: URL
  /// The status, open-play and lock files.
  public let stateDir: URL
  /// The heartbeat the Python status reads.
  public let statusFile: URL
  /// The play still being listened to.
  public let openPlayFile: URL
  /// The single-instance lock.
  public let lockFile: URL
  /// The launch agent's two log files.
  public let logsDir: URL
  /// The launch agent's standard output.
  public let outLog: URL
  /// The launch agent's standard error.
  public let errLog: URL
  /// The installed app bundle.
  public let appBundle: URL
  /// The scrobbler's config file.
  public let configFile: URL
  /// The store's token file.
  public let tokenFile: URL
  /// The signing setting, outside every checkout.
  public let signingConfig: URL
  /// The LaunchAgents folder.
  public let launchAgentsDir: URL
  /// The launch agent's property list.
  public let launchAgentPlist: URL

  /// Every path, each under `home`.
  public init(home: URL) {
    dataDir = home.appendingPathComponent(Layout.dataDir, isDirectory: true)
    queueDir = dataDir.appendingPathComponent("queue", isDirectory: true)
    refusedDir = dataDir.appendingPathComponent("refused", isDirectory: true)
    stateDir = dataDir.appendingPathComponent("state", isDirectory: true)
    statusFile = stateDir.appendingPathComponent("status.json")
    openPlayFile = stateDir.appendingPathComponent("open_play.json")
    lockFile = stateDir.appendingPathComponent("scrobbler.lock")
    logsDir = dataDir.appendingPathComponent("logs", isDirectory: true)
    outLog = logsDir.appendingPathComponent("out.log")
    errLog = logsDir.appendingPathComponent("err.log")
    appBundle = dataDir.appendingPathComponent(Layout.appName, isDirectory: true)
    configFile = home.appendingPathComponent(Layout.configFile)
    tokenFile = home.appendingPathComponent(Layout.tokenFile)
    signingConfig = home.appendingPathComponent(Layout.signingConfig)
    launchAgentsDir = home.appendingPathComponent(Layout.launchAgentsDir, isDirectory: true)
    launchAgentPlist = launchAgentsDir.appendingPathComponent("\(Layout.launchdLabel).plist")
  }

  /// Make the data folder and every folder the app writes in, each new one private to this
  /// user, leaving any that already exist and their contents in place.
  public func makeDataFolders() throws {
    for folder in [queueDir, refusedDir, stateDir, logsDir] {
      try FileIO.makeFolder(folder)
    }
  }
}

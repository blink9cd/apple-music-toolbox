// The scrobbler's executable: it hands its arguments to the tested parser and runs what
// they name. Excluded from coverage as a real-host seam, so it holds no logic a test could
// reach: each piece it wires together is tested on its own in ScrobblerCore.
import Foundation
import ScrobblerCore
import ScrobblerLive
import os

let name = (CommandLine.arguments.first as NSString?)?.lastPathComponent ?? Layout.executable
let log = Logger(subsystem: Layout.bundleID, category: "app")

/// Write `text` and a newline to standard error.
func complain(_ text: String) {
  FileHandle.standardError.write(Data("\(name): \(text)\n".utf8))
}

/// Unix seconds now.
func unixNow() -> Double {
  Date().timeIntervalSince1970
}

/// The config file in `paths`, read afresh on each call.
func configReader(paths: ScrobblerPaths) -> () throws -> ScrobblerConfig {
  { try ScrobblerConfig.load(from: paths.configFile) }
}

/// The token file in `paths`, read afresh on each call.
func tokenReader(paths: ScrobblerPaths) -> () throws(TokenError) -> String {
  { () throws(TokenError) -> String in try TokenReader.read(at: paths.tokenFile, uid: getuid()) }
}

/// The drainer of `queue`, reading the config and the token afresh on each drain, and
/// sending only through the loopback transport.
@MainActor func makeDrainer(paths: ScrobblerPaths, queue: QueueStore) -> QueueDrainer {
  QueueDrainer(
    queue: queue, transport: LoopbackTransport(), config: configReader(paths: paths),
    token: tokenReader(paths: paths), clock: unixNow)
}

/// What is playing now, kept for `status.json` and sent to the relay, which reads the
/// config and the token as the drainer does.
@MainActor func makeSink(paths: ScrobblerPaths) -> FanOutNowPlayingSink {
  FanOutNowPlayingSink([
    StatusNowPlayingSink(),
    NetworkNowPlayingSink(
      transport: LoopbackTransport(timeout: NetworkNowPlayingSink.timeout),
      config: configReader(paths: paths), token: tokenReader(paths: paths)),
  ])
}

/// The coordinator of the live Music bridge and the run-loop timers over the folders in
/// `paths`.
@MainActor func makeCoordinator(paths: ScrobblerPaths) -> Coordinator {
  let queue = QueueStore(queueDir: paths.queueDir, refusedDir: paths.refusedDir)
  return Coordinator(
    bridge: LiveMusicBridge(), scheduler: RunLoopScheduler(),
    drainer: makeDrainer(paths: paths, queue: queue), queue: queue,
    state: StateFiles(stateDir: paths.stateDir), sink: makeSink(paths: paths), clock: unixNow,
    pid: getpid(), newPlayID: { UUID().uuidString.lowercased() })
}

/// The hold that keeps App Nap off while a track plays.
@MainActor func makeActivityHold() -> ActivityHold<any NSObjectProtocol> {
  let process = ProcessInfo.processInfo
  return ActivityHold(
    begin: {
      process.beginActivity(
        options: .userInitiatedAllowingIdleSystemSleep, reason: "scrobbling a playing track")
    }, end: { process.endActivity($0) })
}

/// The instance lock in the data folder of `paths`. Another copy holding it is a retry, so
/// the launch agent starts its copy once that one stops; a lock file that cannot be opened,
/// a link at the data folder included, is a refusal no restart can cure, so the agent
/// leaves it stopped.
func takeLock(in paths: ScrobblerPaths) -> InstanceLock {
  switch InstanceLock.acquire(at: paths.lockFile, owning: paths.dataDir) {
  case .acquired(let lock):
    return lock
  case .held:
    complain("another scrobbler is already running")
    exit(RunExit.retry)
  case .unopenable:
    complain("the instance lock file could not be opened")
    exit(RunExit.refused)
  }
}

/// Run as the scrobbler until the process is stopped: its logs bounded, one copy only, its
/// folders private, the coordinator started once, then the main run loop.
@MainActor func runScrobbler() -> Never {
  let paths = ScrobblerPaths(home: FileManager.default.homeDirectoryForCurrentUser)
  // First, so every start bounds the logs, a start that is about to fail included.
  LogCap.trim(descriptor: STDERR_FILENO, path: paths.errLog)
  LogCap.trim(descriptor: STDOUT_FILENO, path: paths.outLog)
  let lock = takeLock(in: paths)
  do {
    try paths.makeDataFolders()
  } catch {
    complain("the data folders could not be made")
    exit(RunExit.refused)
  }
  let coordinator = makeCoordinator(paths: paths)
  let hold = makeActivityHold()
  coordinator.activityChanged = { hold.set($0) }
  log.info("scrobbler \(Layout.version, privacy: .public) started")
  coordinator.start()
  // The lock, the coordinator and the hold must outlive the run loop, which never returns.
  withExtendedLifetime((lock, coordinator, hold)) { RunLoop.main.run() }
  // The timers keep the run loop busy, so a return means it lost them: stop as a failure,
  // so the launch agent starts a fresh copy.
  complain("the run loop stopped")
  exit(RunExit.retry)
}

switch CommandLineParser.parse(Array(CommandLine.arguments.dropFirst())) {
case .success(.version):
  print(Layout.version)
case .success(.replay(let trace, let out)):
  do {
    print("\(try Replay.run(trace: trace, out: out)) listens written")
  } catch {
    complain("replay failed: \(error)")
    exit(1)
  }
case .success(.run):
  runScrobbler()
case .failure(let error):
  complain(error.message)
  FileHandle.standardError.write(Data(CommandLineParser.usage(program: name).utf8 + [0x0A]))
  exit(2)
}

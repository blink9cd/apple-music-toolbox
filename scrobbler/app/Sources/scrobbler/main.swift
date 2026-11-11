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

/// The instance lock at `url`. Another copy holding it stops this one cleanly; a lock file
/// that cannot be opened is a failure.
func takeLock(at url: URL) -> InstanceLock {
  switch InstanceLock.acquire(at: url) {
  case .acquired(let lock):
    return lock
  case .held:
    complain("another scrobbler is already running")
    exit(0)
  case .unopenable:
    complain("the instance lock file could not be opened")
    exit(1)
  }
}

/// Run as the scrobbler until the process is stopped: one copy only, its folders private,
/// the coordinator started once, then the main run loop.
@MainActor func runScrobbler() -> Never {
  let paths = ScrobblerPaths(home: FileManager.default.homeDirectoryForCurrentUser)
  let lock = takeLock(at: paths.lockFile)
  do {
    try paths.makeDataFolders()
  } catch {
    complain("the data folders could not be made")
    exit(1)
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
  exit(1)
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

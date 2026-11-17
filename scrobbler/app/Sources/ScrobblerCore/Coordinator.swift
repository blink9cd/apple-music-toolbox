import Foundation
import os

/// Runs the play engine against Music, the queue, the sender and the state files.
///
/// The engine decides; the coordinator carries each decision out. `readSnapshot` asks the
/// bridge and feeds the answer back; `startPolling` and `stopPolling` own the repeating
/// position read; `enqueue` writes the queue and starts a drain; `nowPlaying` goes to the
/// sink; `saveOpenPlay` goes to the open-play file. Notices pass through a `Debouncer`. A
/// repeating task feeds the heartbeat and writes `status.json`, and another drains a
/// backlog the sender left.
///
/// No read of Music runs until the system says this app may script it. The first read
/// would otherwise be what raises the Automation prompt, and its Apple event's time limit
/// would withdraw the prompt before the user could answer it. So the coordinator asks
/// first, through the bridge's request, which has no time limit; until the answer is a
/// grant, each read it would have made is skipped and remembered, and each start, notice
/// or poll asks again, one request at a time. A grant makes the reads that were skipped.
///
/// Each request has a generation number, and only the newest one's answer is taken. Music
/// quitting gives up the request in flight, so the next notice or poll asks anew and the
/// old request's answer, if it ever comes, is dropped. While a request waits, the status
/// file carries when it began, written as the request starts and again as its answer
/// arrives, so `status` can tell a prompt nobody has answered from a healthy app. A
/// request that follows a denial or a request that failed writes nothing of its own, since
/// it is made again at every poll: its time reaches the file at the next heartbeat if it
/// is still waiting then.
///
/// Everything runs on the main actor; a drain runs in a `Task` of its own, so a slow store
/// never holds up a notice. A file that cannot be written is logged and stops nothing:
/// the next write tries again.
@MainActor public final class Coordinator {
  /// Seconds between the drains that retry a backlog.
  public static let drainInterval = 60.0

  let bridge: any MusicBridge
  let scheduler: any Scheduler
  let drainer: QueueDrainer
  let queue: QueueStore
  let state: StateFiles
  let sink: any NowPlayingSink
  let clock: () -> Double
  let pid: Int32
  let log = Logger(subsystem: Layout.bundleID, category: "coordinator")

  private var engine: Engine
  private var debouncer = Debouncer()
  /// Inputs waiting for the engine, so an input a running effect produces is handled after
  /// every effect of the input before it.
  private var inbox: [EngineInput] = []
  private var handling = false
  /// The repeating position read, while the engine wants one.
  private var pollTask: (any Cancellable)?
  /// The pending debounce timer; each notice cancels it and sets its own, so one waits.
  private var debounceTask: (any Cancellable)?
  /// The status and drain timers' handles; each runs whether or not its handle is kept.
  private var timers: [any Cancellable] = []

  /// When `start` ran.
  private(set) var startedAt = 0.0
  /// Whether the position read is running, which is when a track is playing.
  private(set) var playing = false
  /// What was last handed to the sink; nil once the play closes.
  private(set) var nowPlaying: NowPlayingRecord?
  /// When a listen was last written to the queue.
  private(set) var lastQueuedAt: Double?
  /// `queue unwritable` while the last listen could not be queued; nil once one is.
  private(set) var queueWriteError: String?
  /// Plays that passed the floor but could not be recorded.
  private(set) var unrecordableCount = 0
  /// Whether the system last refused to let the app script Music.
  private(set) var automationDenied = false
  /// Where the system's permission to script Music stands.
  private var permission = Permission.unknown
  /// The newest permission request's number; an answer carrying any other is dropped.
  private var permissionGeneration = 0
  /// When the request in flight began; nil when none is.
  private(set) var automationAskedAt: Double?
  /// Whether the status file may carry a request's pending time, a write that failed
  /// partway included, so its answer has something to clear there.
  var pendingTimeOnDisk = false
  /// The track whose snapshot read was skipped or timed out while not granted, read once
  /// the grant arrives.
  private var owedSnapshot: String?
  /// Whether a position read (at start, or a poll) was skipped while not granted.
  private var owedPosition = false
  /// The drain started last, so a test can wait for it.
  private(set) var pendingDrain: Task<Void, Never>?

  /// Called with true when a track starts playing and false when it stops, so the app can
  /// hold off App Nap while it plays.
  public var activityChanged: ((Bool) -> Void)?

  /// A coordinator of `bridge` and `scheduler`, sending through `drainer` from `queue`,
  /// saving to `state` and publishing to `sink`. `clock` gives Unix seconds, `pid` is the
  /// app's own, and `newPlayID` makes each new play's UUID.
  public init(
    bridge: any MusicBridge, scheduler: any Scheduler, drainer: QueueDrainer, queue: QueueStore,
    state: StateFiles, sink: any NowPlayingSink, clock: @escaping () -> Double, pid: Int32,
    newPlayID: @escaping @Sendable () -> String
  ) {
    self.bridge = bridge
    self.scheduler = scheduler
    self.drainer = drainer
    self.queue = queue
    self.state = state
    self.sink = sink
    self.clock = clock
    self.pid = pid
    engine = Engine(newPlayID: newPlayID)
  }

  /// Take up a saved play, read where Music is, then listen for notices, start the timers,
  /// write the first status and send any backlog.
  public func start() {
    startedAt = clock()
    if let play = state.readOpenPlay(OpenPlay.self) { feed(.restored(play, at: startedAt)) }
    if bridge.isMusicRunning() { readPosition() } else { feed(.musicQuit(at: clock())) }
    bridge.start(
      onNotice: { [weak self] in self?.offer($0) },
      onQuit: { [weak self] in self?.musicQuit() })
    startTimers()
    writeStatus()
    drainIfBacklogged()
  }

  /// The heartbeat-and-status timer and the backlog timer.
  private func startTimers() {
    timers.append(
      scheduler.repeating(every: Engine.heartbeatInterval) { [weak self] in self?.heartbeat() })
    timers.append(
      scheduler.repeating(every: Self.drainInterval) { [weak self] in self?.drainIfBacklogged() })
  }

  /// A notice from Music, held until its burst has passed.
  private func offer(_ notice: PlayerNotice) {
    let now = clock()
    let deadline = debouncer.offer(notice, at: now)
    debounceTask?.cancel()
    debounceTask = scheduler.once(after: deadline - now) { [weak self] in
      self?.fireNotice(due: deadline)
    }
  }

  /// The debounced notice whose window ended at `due`.
  ///
  /// Each notice cancels the timer before it, so the timer that fires is the newest one's
  /// and the debouncer holds that notice. It is asked at the deadline this timer was set
  /// for, not at the clock, so a timer that fires a hair early cannot lose the notice.
  private func fireNotice(due: Double) {
    debouncer.fire(at: due).map { feed(.notice($0, at: clock())) }
    // A notice is Music's word that something changed, so a denial or an unknown answer is
    // asked about again; once decided, asking raises no prompt.
    if permission != .granted { askPermission() }
  }

  /// Music quit. A request in flight is given up first: its answer may never come, and one
  /// that does come is about the Music that is gone.
  private func musicQuit() {
    let abandoned = abandonPermissionRequest()
    feed(.musicQuit(at: clock()))
    if abandoned { writeStatus() }
  }

  private func heartbeat() {
    feed(.heartbeat(at: clock()))
    writeStatus()
  }

  /// One position read, once permitted: an empty answer is Music gone, a refusal is the
  /// system's denial, a timeout asks for permission again before the next read, and a
  /// malformed answer is skipped, since the next poll reads again.
  private func readPosition() {
    guard permission == .granted else {
      owedPosition = true
      return askPermission()
    }
    switch bridge.readPosition() {
    case .success(let read): feed(.position(read, at: clock()))
    case .failure(.musicNotRunning): feed(.musicQuit(at: clock()))
    case .failure(.automationDenied):
      permission = .denied
      feed(.automation(allowed: false, at: clock()))
    case .failure(.timedOut): readTimedOut()
    case .failure(let error): log.error("position read failed: \(String(describing: error))")
    }
  }

  /// One snapshot read of `persistentID`, its answer fed back to the engine. Skipped while
  /// not permitted, and a timed-out one is owed, so either is read once the grant arrives.
  private func readSnapshot(of persistentID: String) {
    guard permission == .granted else {
      owedSnapshot = persistentID
      return
    }
    switch bridge.readSnapshot() {
    case .success(let snapshot): feed(.snapshot(snapshot, at: clock()))
    case .failure(.timedOut):
      owedSnapshot = persistentID
      readTimedOut()
    case .failure(let error):
      feed(.snapshotFailed(persistentID: persistentID, error, at: clock()))
    }
  }

  /// A read Music did not answer in time. The permission is asked again before the next
  /// read: a prompt holding the read is answered without a time limit, and a grant already
  /// given answers at once.
  private func readTimedOut() {
    log.error("a Music read timed out; asking for permission before the next read")
    permission = .unknown
  }

  /// Ask the system for permission, unless a request is already in flight. Its answer may
  /// come before this returns; when it has not, the status file is written now, so the
  /// time the request began is on disk for as long as it waits.
  ///
  /// Not so after a denial or a request that failed: each came without a prompt, the
  /// next most likely will too, and it is asked at every poll, so writing the file at
  /// each would be a write a second for as long as that lasts. Should such a request hang
  /// after all, the heartbeat's write carries its time, at most one heartbeat late.
  ///
  /// A request that never returns while Music stays running is not asked again on a
  /// timer: nothing here can tell it from a prompt the user has not answered yet, and a
  /// second request would not answer the first. `status` is what surfaces it, from the
  /// time in the status file. Only Music quitting gives a request up.
  private func askPermission() {
    guard permission != .asking else { return }
    let promptLikely = permission != .denied && permission != .unsettled
    permission = .asking
    permissionGeneration += 1
    let generation = permissionGeneration
    automationAskedAt = clock()
    bridge.requestPermission { [weak self] in
      self?.permissionAnswered($0, generation: generation)
    }
    if promptLikely, automationAskedAt != nil { writeStatus() }
  }

  /// Give up the request in flight, if there is one: its number is retired, so its answer
  /// is dropped, the reads owed to it are forgotten with the Music they were of, and the
  /// next notice or poll asks anew. Returns whether there was one.
  private func abandonPermissionRequest() -> Bool {
    guard permission == .asking else { return false }
    permissionGeneration += 1
    permission = .unknown
    automationAskedAt = nil
    owedSnapshot = nil
    owedPosition = false
    return true
  }

  /// The system's answer to request number `generation`; one that is not the newest
  /// request's is dropped. A grant makes the reads that were skipped: the owed snapshot,
  /// then an owed position read, which picks up the play under way. A denial is reported.
  /// Music gone is handled as a position read finding it gone, and any other answer is
  /// logged and asked again at the next notice or poll. Once the answer is handled the
  /// status file is written if what it says of the request has changed: a pending time
  /// there to clear, or a denial that began or ended. So no pending time outlives its
  /// request there, and a denial or a failed request repeated at every poll writes nothing.
  private func permissionAnswered(_ answer: AutomationPermission, generation: Int) {
    guard generation == permissionGeneration else {
      return log.info("dropped the answer of a permission request that was given up")
    }
    automationAskedAt = nil
    let wasDenied = automationDenied
    defer { if pendingTimeOnDisk || automationDenied != wasDenied { writeStatus() } }
    switch answer {
    case .granted:
      permission = .granted
      feed(.automation(allowed: true, at: clock()))
      if let persistentID = owedSnapshot {
        owedSnapshot = nil
        readSnapshot(of: persistentID)
      }
      // A snapshot that timed out again leaves its retry to the next notice or poll, so a
      // Music that keeps timing out is asked at the poll's pace, never in a loop.
      guard permission == .granted, owedPosition else { return }
      owedPosition = false
      readPosition()
    case .denied:
      permission = .denied
      feed(.automation(allowed: false, at: clock()))
    case .musicNotRunning:
      // Music running now means it quit and came back while the request waited, unseen:
      // the answer is about the Music that is gone, so the play open now is left alone
      // and the next notice or poll asks again.
      // That next request may well raise the prompt, so it is asked as one not yet made.
      permission = .unknown
      guard !bridge.isMusicRunning() else { return }
      owedSnapshot = nil
      owedPosition = false
      feed(.musicQuit(at: clock()))
    case .other(let status):
      permission = .unsettled
      log.error("the Automation permission request failed: status \(status, privacy: .public)")
    }
  }

  /// Hand `input` to the engine and carry out its effects, then any input they produced.
  private func feed(_ input: EngineInput) {
    inbox.append(input)
    guard !handling else { return }
    handling = true
    defer { handling = false }
    while !inbox.isEmpty {
      engine.handle(inbox.removeFirst()).forEach(perform)
    }
  }

  /// Carry out one effect.
  private func perform(_ effect: EngineEffect) {
    switch effect {
    case .readSnapshot(let persistentID): readSnapshot(of: persistentID)
    case .startPolling: setPolling(true)
    case .stopPolling: setPolling(false)
    case .enqueue(let record): enqueue(record)
    case .nowPlaying(let record):
      nowPlaying = record
      sink.publish(record)
    case .saveOpenPlay(let play): save(play)
    case .unrecordable: unrecordableCount += 1
    case .automationDenied(let denied): automationDenied = denied
    }
  }

  /// Start or stop the repeating position read, and tell the app.
  private func setPolling(_ wanted: Bool) {
    pollTask?.cancel()
    pollTask =
      wanted
      ? scheduler.repeating(every: Engine.pollInterval) { [weak self] in self?.readPosition() }
      : nil
    playing = wanted
    activityChanged?(wanted)
  }

  /// Write `record` to the queue and start a drain. One too large for the queue goes to the
  /// refused folder instead: it is counted there, so it neither sets `lastQueuedAt` nor
  /// counts as a write error.
  private func enqueue(_ record: ListenRecord) {
    do {
      switch try queue.enqueue(record) {
      case .queued: lastQueuedAt = clock()
      case .refused: log.error("listen refused: larger than the store's per-listen limit")
      }
      queueWriteError = nil
    } catch {
      queueWriteError = "queue unwritable"
      log.error("listen not queued: \(String(describing: error))")
    }
    startDrain()
  }

  /// Save the open play, or remove the saved one. What is playing now ends with its play:
  /// when the play closes, or another opens whose own record could not be built, the
  /// copy names a play that is no longer open.
  private func save(_ play: OpenPlay?) {
    if play?.playID != nowPlaying?.payload.first?.trackMetadata.additionalInfo.lsPlayID {
      nowPlaying = nil
    }
    do {
      try state.writeOpenPlay(play)
    } catch {
      log.error("open play not saved: \(String(describing: error))")
    }
  }

  /// Start a drain unless the queue is known to be empty; one that cannot be listed is
  /// drained too, so the drainer records why.
  private func drainIfBacklogged() {
    guard (try? queue.pending().isEmpty) != true else { return }
    startDrain()
  }

  /// Start a drain in its own task; the drainer turns away one that overlaps another.
  private func startDrain() {
    pendingDrain = Task { [drainer] in _ = await drainer.drain() }
  }
}

/// Where the coordinator stands on the system's permission to script Music.
private enum Permission {
  /// Not asked yet, or not since Music was last gone or a read timed out: asking may
  /// raise the prompt.
  case unknown
  /// The last request failed, which came without a prompt; asked again at the next
  /// notice or poll.
  case unsettled
  /// A request is in flight; it may be waiting on the user.
  case asking
  /// Reads may run.
  case granted
  /// The system refused; asked again at the next notice or poll.
  case denied
}

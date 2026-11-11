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
  /// Whether the last snapshot read was refused by the system.
  private(set) var automationDenied = false
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
  }

  private func musicQuit() {
    feed(.musicQuit(at: clock()))
  }

  private func heartbeat() {
    feed(.heartbeat(at: clock()))
    writeStatus()
  }

  /// One position read: an empty answer is Music gone, and a malformed one is skipped,
  /// since the next poll reads again.
  private func readPosition() {
    switch bridge.readPosition() {
    case .success(let read): feed(.position(read, at: clock()))
    case .failure(.musicNotRunning): feed(.musicQuit(at: clock()))
    case .failure(let error): log.error("position read failed: \(String(describing: error))")
    }
  }

  /// One snapshot read of `persistentID`, its answer fed back to the engine.
  private func readSnapshot(of persistentID: String) {
    switch bridge.readSnapshot() {
    case .success(let snapshot): feed(.snapshot(snapshot, at: clock()))
    case .failure(let error):
      feed(.snapshotFailed(persistentID: persistentID, error, at: clock()))
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

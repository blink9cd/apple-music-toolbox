import Foundation
import Testing

@testable import ScrobblerCore

// The coordinator's fakes. The transport fake is `FakeTransport`, beside the drainer's own
// test rig, so one type of that name serves both suites.

/// A Music bridge answering from settable results and logging every call.
@MainActor
final class FakeMusicBridge: MusicBridge {
  /// Whether Music is running.
  var running = true
  /// What the next position read returns.
  var position: Result<PositionRead, SnapshotReadError> = .failure(.musicNotRunning)
  /// What the next snapshot read returns.
  var snapshot: Result<TrackSnapshot, SnapshotReadError> = .failure(.noCurrentTrack)
  /// Each call, by name, in order.
  private(set) var calls: [String] = []
  /// The notice handler `start` was given.
  private var onNotice: (@MainActor (PlayerNotice) -> Void)?
  /// The quit handler `start` was given.
  private var onQuit: (@MainActor () -> Void)?

  func start(
    onNotice: @escaping @MainActor (PlayerNotice) -> Void, onQuit: @escaping @MainActor () -> Void
  ) {
    calls.append("start")
    self.onNotice = onNotice
    self.onQuit = onQuit
  }

  func isMusicRunning() -> Bool {
    calls.append("running")
    return running
  }

  func readPosition() -> Result<PositionRead, SnapshotReadError> {
    calls.append("position")
    return position
  }

  func readSnapshot() -> Result<TrackSnapshot, SnapshotReadError> {
    calls.append("snapshot")
    return snapshot
  }

  /// Post `notice` as Music would.
  func post(_ notice: PlayerNotice) {
    onNotice?(notice)
  }

  /// Quit Music.
  func quit() {
    running = false
    onQuit?()
  }

  /// How many times `name` was called.
  func count(_ name: String) -> Int {
    calls.filter { $0 == name }.count
  }
}

/// A scheduler on a manual clock: `advance(by:)` fires each due task in time order.
@MainActor
final class FakeScheduler: Scheduler {
  /// One scheduled task.
  final class Job: Cancellable {
    var due: Double
    let every: Double?
    let body: @MainActor () -> Void
    var canceled = false

    init(due: Double, every: Double?, body: @escaping @MainActor () -> Void) {
      self.due = due
      self.every = every
      self.body = body
    }

    func cancel() {
      canceled = true
    }
  }

  /// The manual clock, in Unix seconds.
  var now: Double
  /// Every task scheduled and not yet finished.
  private(set) var jobs: [Job] = []

  init(now: Double) {
    self.now = now
  }

  func repeating(every: Double, _ body: @escaping @MainActor () -> Void) -> any Cancellable {
    add(Job(due: now + every, every: every, body: body))
  }

  func once(after: Double, _ body: @escaping @MainActor () -> Void) -> any Cancellable {
    add(Job(due: now + after, every: nil, body: body))
  }

  /// Move the clock on by `seconds`, firing each task as its time comes.
  func advance(by seconds: Double) {
    let end = now + seconds
    while let job = nextDue(by: end) {
      now = job.due
      if let every = job.every { job.due += every } else { job.canceled = true }
      job.body()
    }
    now = end
  }

  /// The live tasks repeating every `seconds`.
  func repeatingJobs(every seconds: Double) -> [Job] {
    jobs.filter { !$0.canceled && $0.every == seconds }
  }

  /// The one-shot tasks still waiting to run.
  func pendingOnceJobs() -> [Job] {
    jobs.filter { !$0.canceled && $0.every == nil }
  }

  private func add(_ job: Job) -> Job {
    jobs.append(job)
    return job
  }

  /// The earliest live task due by `end`, the first scheduled winning a tie.
  private func nextDue(by end: Double) -> Job? {
    jobs.removeAll(where: \.canceled)
    return jobs.filter { $0.due <= end }.min { $0.due < $1.due }
  }
}

/// A now-playing sink that keeps every record it is given.
@MainActor
final class RecordingSink: NowPlayingSink {
  private(set) var records: [NowPlayingRecord] = []

  func publish(_ record: NowPlayingRecord) {
    records.append(record)
  }
}

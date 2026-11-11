import Foundation
import Testing

@testable import ScrobblerCore

/// A coordinator wired to fakes in a temp folder, its clock the fake scheduler's.
@MainActor
final class CoordinatorRig {
  let temp: TempFolder
  let bridge = FakeMusicBridge()
  let scheduler = FakeScheduler(now: base)
  let sink = RecordingSink()
  let transport: FakeTransport
  let queue: QueueStore
  let state: StateFiles
  let drainer: QueueDrainer
  private(set) var coordinator: Coordinator!
  /// Each value `activityChanged` was called with, in order.
  private(set) var activity: [Bool] = []

  init(_ answers: [TransportResult] = []) throws {
    temp = try TempFolder()
    queue = QueueStore(queueDir: temp.child("queue"), refusedDir: temp.child("refused"))
    state = StateFiles(stateDir: temp.child("state"))
    transport = FakeTransport(answers)
    let scheduler = scheduler
    drainer = QueueDrainer(
      queue: queue, transport: transport, config: { ScrobblerConfig() },
      token: { () throws(TokenError) -> String in testToken }, clock: { scheduler.now })
    coordinator = Coordinator(
      bridge: bridge, scheduler: scheduler, drainer: drainer, queue: queue, state: state,
      sink: sink, clock: { scheduler.now }, pid: 4242, newPlayID: countingIDs())
    coordinator.activityChanged = { [unowned self] in activity.append($0) }
  }

  /// Music playing `id` at `positionMs`, as the next position read finds it.
  func playing(_ positionMs: Int, _ id: String = trackOne) {
    bridge.position = .success(position(.playing, positionMs, id))
  }

  /// Play `id` on, one poll at a time, from `fromMs` for `seconds`.
  func playOn(from fromMs: Int, seconds: Int, _ id: String = trackOne) {
    for step in stride(from: 2, through: seconds, by: 2) {
      playing(fromMs + step * 1_000, id)
      scheduler.advance(by: Engine.pollInterval)
    }
  }

  /// Wait for the drain the coordinator last started.
  func settle() async {
    await coordinator.pendingDrain?.value
  }

  /// The status file as JSON.
  func status() throws -> [String: Any] {
    let data = try Data(contentsOf: state.statusFile)
    return try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
  }
}

import Foundation
import Testing

@testable import ScrobblerCore

// Whole scenarios through the coordinator, every host seam a fake: Music, the timers, the
// store, and a temp folder for the queue and the state files.

/// The listen a POST carried.
private func postedListen(_ call: FakeTransport.Call) throws -> Listen {
  try #require(try RecordCoding.decode(ListenRecord.self, from: call.body).payload.first)
}

@MainActor @Test func aTrackHeardFortySecondsThenChangedIsQueuedOnceAndPostedOnce() async throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 40)
  rig.playing(0, trackTwo)
  rig.scheduler.advance(by: Engine.pollInterval)
  await rig.settle()
  let calls = await rig.transport.calls
  #expect(calls.count == 1)
  let listen = try postedListen(try #require(calls.first))
  #expect(listen.trackMetadata.additionalInfo.durationPlayed == 40)
  #expect(listen.trackMetadata.trackName == snapshot().name)
  #expect(listen.listenedAt == Int(base))
  #expect(try rig.queue.pending().isEmpty)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["last_queued_at"] as? Double == base + 42)
}

@MainActor @Test func musicNotRunningAtStartPollsNothing() throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.scheduler.advance(by: 60)
  #expect(rig.bridge.count("position") == 0)
  #expect(rig.scheduler.repeatingJobs(every: Engine.pollInterval).isEmpty)
  #expect(rig.activity.isEmpty)
  #expect(try rig.status()["music_running"] as? Bool == false)
}

@MainActor @Test func aRefusedSnapshotSetsAutomationDeniedInTheNextStatus() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .failure(.automationDenied)
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: Int(Engine.heartbeatInterval))
  #expect(try rig.status()["automation_denied"] as? Bool == true)
}

@MainActor @Test func aRestoredPlayOfTheSameTrackContinues() throws {
  let rig = try CoordinatorRig()
  try rig.state.writeOpenPlay(savedPlay())
  rig.playing(120_000)
  rig.coordinator.start()
  rig.playOn(from: 120_000, seconds: 4)
  let saved = try #require(rig.state.readOpenPlay(OpenPlay.self))
  #expect(saved.playID == savedPlay().playID)
  #expect(saved.heardSeconds == 44)
  #expect(rig.activity == [true])
}

@MainActor @Test func aRestoredPlayOfAnotherTrackClosesWithItsSavedSeconds() async throws {
  let rig = try CoordinatorRig()
  try rig.state.writeOpenPlay(savedPlay())
  rig.playing(3_000, trackTwo)
  rig.coordinator.start()
  await rig.settle()
  let listen = try postedListen(try #require(await rig.transport.calls.first))
  #expect(listen.trackMetadata.additionalInfo.lsPlayID == savedPlay().playID)
  #expect(listen.trackMetadata.additionalInfo.durationPlayed == 40)
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.persistentID == trackTwo)
}

@MainActor @Test func aRestoredPlayWithMusicNotRunningCloses() async throws {
  let rig = try CoordinatorRig()
  try rig.state.writeOpenPlay(savedPlay())
  rig.bridge.running = false
  rig.coordinator.start()
  await rig.settle()
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.state.readOpenPlay(OpenPlay.self) == nil)
  #expect(rig.activity == [true, false])
}

@MainActor @Test func theStatusIsWrittenEveryThirtySecondsWithNothingPlaying() throws {
  let rig = try CoordinatorRig()
  rig.bridge.position = .success(position(.stopped, 0, nil))
  rig.coordinator.start()
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  let status = try rig.status()
  #expect(status["heartbeat_at"] as? Double == base + Engine.heartbeatInterval)
  #expect(status["started_at"] as? Double == base)
  #expect(status["pid"] as? Int == 4242)
  #expect(status["music_running"] as? Bool == true)
  #expect(status["playing"] as? Bool == false)
  #expect(status["now_playing"] is NSNull)
  #expect(status["last_send_error"] is NSNull)
  #expect(status.count == 16)
}

@MainActor @Test func activityTurnsOnWithPlayAndOffWithPause() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  #expect(rig.activity == [true])
  rig.playOn(from: 0, seconds: 6)
  rig.bridge.post(notice(.paused))
  rig.scheduler.advance(by: Debouncer.window)
  #expect(rig.activity == [true, false])
  #expect(rig.scheduler.repeatingJobs(every: Engine.pollInterval).isEmpty)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["playing"] as? Bool == false)
  let shown = try #require(try rig.status()["now_playing"] as? [String: Any])
  #expect(shown["listen_type"] as? String == "playing_now")
  #expect(rig.sink.records.last?.payload.first?.trackMetadata.additionalInfo.lsState == .paused)
}

@MainActor @Test func aBurstOfNoticesReachesTheEngineAsItsNewest() throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.bridge.running = true
  rig.bridge.post(notice(.paused))
  rig.scheduler.advance(by: 0.025)
  rig.bridge.post(notice(.playing))
  rig.scheduler.advance(by: Debouncer.window - 0.01)
  #expect(rig.activity.isEmpty)
  #expect(rig.bridge.count("snapshot") == 0)
  #expect(rig.sink.records.isEmpty)
  rig.scheduler.advance(by: 0.01)
  #expect(rig.activity == [true])
  #expect(rig.bridge.count("snapshot") == 1)
  #expect(rig.sink.records.count == 1)
  #expect(rig.sink.records.first?.payload.first?.trackMetadata.additionalInfo.lsState == .playing)
}

@MainActor @Test func aBurstOfNoticesLeavesOneDebounceTimerPending() throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  for state in [PlayerState.paused, .playing, .paused] {
    rig.bridge.post(notice(state))
    rig.scheduler.advance(by: 0.025)
  }
  #expect(rig.scheduler.pendingOnceJobs().count == 1)
}

@MainActor @Test func aTrackChangeWithNoNowPlayingClearsTheOldOneFromStatus() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 10)
  // The reads find the new track too, so no read reopens a play of the old one.
  rig.playing(0, trackTwo)
  rig.bridge.post(notice(.playing, trackTwo, artist: nil))
  rig.scheduler.advance(by: Debouncer.window)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["now_playing"] is NSNull)
}

@MainActor @Test func musicQuittingClosesThePlay() async throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 10)
  rig.bridge.quit()
  #expect(rig.scheduler.repeatingJobs(every: Engine.pollInterval).isEmpty)
  await rig.settle()
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.activity == [true, false])
  #expect(rig.state.readOpenPlay(OpenPlay.self) == nil)
}

@MainActor @Test func aPositionReadFindingMusicGoneClosesThePlay() async throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 10)
  rig.bridge.position = .failure(.musicNotRunning)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.scheduler.repeatingJobs(every: Engine.pollInterval).isEmpty)
  await rig.settle()
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.activity == [true, false])
}

@MainActor @Test func aMalformedPositionReadIsSkipped() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.bridge.position = .failure(.malformed("expected 4 fields, got 2"))
  rig.scheduler.advance(by: Engine.pollInterval)
  rig.playOn(from: 2_000, seconds: 4)
  #expect(rig.activity == [true])
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.heardSeconds == 6)
}

@MainActor @Test func aPlayThatCannotBeRecordedIsCounted() throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.bridge.running = true
  rig.bridge.post(notice(.playing, artist: nil))
  rig.scheduler.advance(by: Debouncer.window)
  rig.playOn(from: 0, seconds: 10)
  rig.bridge.post(notice(.playing, trackTwo))
  rig.scheduler.advance(by: Debouncer.window)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["unrecordable_count"] as? Int == 1)
  #expect(try rig.queue.pending().isEmpty)
}

@MainActor @Test func aBacklogIsDrainedAtStartAndRetriedEveryMinute() async throws {
  let rig = try CoordinatorRig([.failed(reason: "refused"), .failed(reason: "refused")])
  try rig.queue.enqueue(try queuedListen(listenedAt: Int(base) - 7_200))
  rig.bridge.running = false
  rig.coordinator.start()
  await rig.settle()
  #expect(await rig.transport.calls.count == 1)
  rig.scheduler.advance(by: Coordinator.drainInterval)
  await rig.settle()
  #expect(await rig.transport.calls.count == 2)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  let status = try rig.status()
  #expect(status["queue_backlog"] as? Int == 1)
  #expect(status["oldest_queued_at"] as? Double == base - 7_200)
  #expect(status["last_send_error"] as? String == "store unreachable")
  #expect(status["refused_count"] as? Int == 0)
}

@MainActor @Test func aPlayTooLargeToQueueIsRefusedAndSendsNothing() async throws {
  let rig = try CoordinatorRig()
  var large = snapshot()
  large.name = longestField
  large.artist = longestField
  large.album = longestField
  large.composer = longestField
  rig.bridge.snapshot = .success(large)
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 40)
  rig.playing(0, trackTwo)
  rig.scheduler.advance(by: Engine.pollInterval)
  await rig.settle()
  #expect(await rig.transport.calls.isEmpty)
  #expect(try rig.queue.pending().isEmpty)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  let status = try rig.status()
  #expect(status["refused_count"] as? Int == 1)
  #expect(status["last_send_error"] is NSNull)
  #expect(status["last_queued_at"] is NSNull)
}

@MainActor @Test func anEmptyQueueIsNotDrainedByTheMinuteTimer() async throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.scheduler.advance(by: Coordinator.drainInterval)
  #expect(rig.coordinator.pendingDrain == nil)
}

@MainActor @Test func aQueueThatCannotBeWrittenIsReported() throws {
  let rig = try CoordinatorRig()
  try FileIO.makeFolder(rig.queue.queueDir)
  try setMode(0o500, of: rig.queue.queueDir)
  defer { try? setMode(0o700, of: rig.queue.queueDir) }
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 10)
  rig.bridge.quit()
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  let status = try rig.status()
  #expect(status["last_send_error"] as? String == "queue unwritable")
  #expect(status["last_queued_at"] is NSNull)
}

@MainActor @Test func aQueueThatCannotBeListedIsReported() throws {
  let rig = try CoordinatorRig()
  try writeFile("not a folder", to: rig.queue.queueDir)
  rig.bridge.running = false
  rig.coordinator.start()
  let status = try rig.status()
  #expect(status["last_send_error"] as? String == "queue unreadable")
  #expect(status["queue_backlog"] as? Int == 0)
}

@MainActor @Test func stateFilesThatCannotBeWrittenStopNothing() throws {
  let rig = try CoordinatorRig()
  let stateDir = rig.state.statusFile.deletingLastPathComponent()
  try FileIO.makeFolder(stateDir)
  try setMode(0o500, of: stateDir)
  defer { try? setMode(0o700, of: stateDir) }
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.playOn(from: 0, seconds: 4)
  #expect(rig.activity == [true])
  #expect(!FileManager.default.fileExists(atPath: rig.state.statusFile.path))
}

@MainActor @Test func theStatusSinkKeepsTheNewestRecord() throws {
  let sink = StatusNowPlayingSink()
  #expect(sink.latest == nil)
  let first = try RecordCoding.decode(NowPlayingRecord.self, from: minimalNowPlaying())
  var second = first
  second.payload[0].trackMetadata.trackName = "Second Lantern"
  sink.publish(first)
  sink.publish(second)
  #expect(sink.latest == second)
}

@MainActor @Test func forgedNoticesAloneQueueNothing() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .failure(.musicNotRunning)
  rig.coordinator.start()
  for _ in 0..<5 {
    rig.bridge.post(notice(.playing))
    rig.scheduler.advance(by: 0.5)
    rig.bridge.post(notice(.paused))
    rig.scheduler.advance(by: 0.5)
  }
  rig.bridge.post(notice(.stopped))
  rig.scheduler.advance(by: 1)
  #expect(rig.bridge.count("snapshot") >= 1)
  #expect(rig.bridge.count("position") == 1)
  #expect(try rig.queue.pending().isEmpty)
}

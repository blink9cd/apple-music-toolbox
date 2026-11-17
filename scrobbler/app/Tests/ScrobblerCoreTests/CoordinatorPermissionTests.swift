import Foundation
import Testing

@testable import ScrobblerCore

// The permission step: no read of Music runs until the system says this app may script it,
// and the request that asks the user has no time limit, so it is held here as long as a
// test likes. Every host seam is a fake.

/// The status file's `automation_denied`, written at the next heartbeat.
@MainActor private func deniedInStatus(_ rig: CoordinatorRig) throws -> Bool? {
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  return try rig.status()["automation_denied"] as? Bool
}

/// Post `notice` and let its debounce window pass.
@MainActor private func deliver(_ notice: PlayerNotice, to rig: CoordinatorRig) {
  rig.bridge.post(notice)
  rig.scheduler.advance(by: Debouncer.window)
}

@MainActor @Test func noReadRunsWhileThePermissionPromptIsUnanswered() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = nil
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  deliver(notice(.playing), to: rig)
  rig.scheduler.advance(by: Engine.pollInterval * 3)
  #expect(rig.bridge.count("position") == 0)
  #expect(rig.bridge.count("snapshot") == 0)
  // One request stays in flight however many notices and polls come while it waits.
  #expect(rig.bridge.count("permission") == 1)
}

@MainActor @Test func aGrantReadsThePlayUnderWayAtOnce() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = nil
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(30_000)
  rig.coordinator.start()
  #expect(rig.activity.isEmpty)
  rig.bridge.answerPermission(.granted)
  #expect(rig.bridge.count("position") == 1)
  #expect(rig.bridge.count("snapshot") == 1)
  #expect(rig.activity == [true])
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.snapshot == snapshot())
}

@MainActor @Test func aGrantReadsTheSnapshotANoticeAskedForWhileWaiting() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = nil
  rig.bridge.snapshot = .success(snapshot())
  rig.bridge.running = false
  rig.coordinator.start()
  rig.bridge.running = true
  deliver(notice(.playing), to: rig)
  #expect(rig.bridge.count("permission") == 1)
  rig.bridge.answerPermission(.granted)
  #expect(rig.bridge.count("snapshot") == 1)
  // No position read was skipped: the notice started the polls, and the next one reads.
  #expect(rig.bridge.count("position") == 0)
  let shown = try #require(rig.sink.records.last?.payload.first?.trackMetadata)
  #expect(shown.trackName == snapshot().name)
}

@MainActor @Test func musicNotRunningAtStartAsksNothing() throws {
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.scheduler.advance(by: 60)
  #expect(rig.bridge.count("permission") == 0)
}

@MainActor @Test func aDenialIsReportedAndReadsNothing() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = .denied
  rig.playing(0)
  rig.coordinator.start()
  #expect(try deniedInStatus(rig) == true)
  #expect(rig.bridge.count("position") == 0)
}

@MainActor @Test func aDenialIsCheckedAgainOnEachNoticeAndClearsOnceGranted() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = .denied
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  deliver(notice(.playing), to: rig)
  let asked = rig.bridge.count("permission")
  #expect(asked >= 2)
  rig.bridge.permission = .granted
  deliver(notice(.playing, trackTwo), to: rig)
  #expect(rig.bridge.count("permission") == asked + 1)
  #expect(rig.bridge.count("position") >= 1)
  #expect(try deniedInStatus(rig) == false)
}

@MainActor @Test func aPollWhileNotGrantedAsksAgainAfterAnUnexpectedAnswer() throws {
  let rig = try CoordinatorRig()
  rig.bridge.permission = .other(-50)
  rig.coordinator.start()
  deliver(notice(.playing), to: rig)
  let asked = rig.bridge.count("permission")
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == asked + 1)
  #expect(rig.bridge.count("position") == 0)
  rig.bridge.permission = .granted
  rig.playing(4_000)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("position") == 1)
  #expect(try deniedInStatus(rig) == false)
}

@MainActor @Test func musicQuittingBeforeTheAnswerClosesARestoredPlay() async throws {
  let rig = try CoordinatorRig()
  try rig.state.writeOpenPlay(savedPlay())
  rig.bridge.permission = nil
  rig.coordinator.start()
  // Music goes without the quit notice arriving, so the answer is the first word of it.
  rig.bridge.running = false
  rig.bridge.answerPermission(.musicNotRunning)
  await rig.settle()
  #expect(rig.bridge.count("position") == 0)
  #expect(await rig.transport.calls.count == 1)
  #expect(rig.state.readOpenPlay(OpenPlay.self) == nil)
}

@MainActor @Test func aRefusedPositionReadSetsAutomationDeniedAndAsksAgain() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.bridge.position = .failure(.automationDenied)
  rig.bridge.permission = .denied
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == 1)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == 2)
  #expect(rig.bridge.count("position") == 2)
  #expect(try deniedInStatus(rig) == true)
}

@MainActor @Test func aTimedOutPositionReadIsReadAgainOnTheNextPoll() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  rig.bridge.position = .failure(.timedOut)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == 1)
  rig.playing(4_000)
  rig.scheduler.advance(by: Engine.pollInterval)
  // The permission is asked again, without a prompt once decided, then the read runs.
  #expect(rig.bridge.count("permission") == 2)
  #expect(rig.bridge.count("position") == 3)
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.lastPositionMs == 4_000)
}

@MainActor @Test func aTimedOutSnapshotReadIsReadAgainOnceGranted() throws {
  let rig = try CoordinatorRig()
  rig.bridge.snapshot = .failure(.timedOut)
  rig.playing(0)
  rig.coordinator.start()
  #expect(rig.bridge.count("snapshot") == 1)
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(2_000)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == 2)
  #expect(rig.bridge.count("snapshot") == 2)
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.snapshot == snapshot())
}

@Test func aPermissionAnswerSetsAndClearsTheDenialOnce() {
  var engine = makeEngine()
  #expect(engine.handle(.automation(allowed: true, at: base)).isEmpty)
  #expect(labels(engine.handle(.automation(allowed: false, at: base + 1))) == ["denied true"])
  #expect(engine.handle(.automation(allowed: false, at: base + 2)).isEmpty)
  #expect(labels(engine.handle(.automation(allowed: true, at: base + 3))) == ["denied false"])
}

@Test func aGrantClearsADenialASnapshotReadReported() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.snapshotFailed(persistentID: trackOne, .automationDenied, at: base + 101))
  #expect(labels(engine.handle(.automation(allowed: true, at: base + 102))) == ["denied false"])
}

@Test(arguments: [
  (0, AutomationPermission.granted), (-1743, .denied), (-1744, .denied),
  (-600, .musicNotRunning), (-609, .musicNotRunning), (-50, .other(-50)),
])
func eachSystemAnswerIsMapped(status: Int, expected: AutomationPermission) {
  #expect(AutomationPermission(status: status) == expected)
}

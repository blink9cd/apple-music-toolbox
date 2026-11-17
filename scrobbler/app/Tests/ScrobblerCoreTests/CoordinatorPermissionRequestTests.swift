import Foundation
import Testing

@testable import ScrobblerCore

// The permission request's own life: the pending time the status file carries while a
// request waits, the request given up when Music quits, and the answers that arrive too
// late to mean anything. Every host seam is a fake, and the fake bridge holds as many
// requests as a test leaves unanswered, oldest first.

/// Post `notice` and let its debounce window pass.
@MainActor private func deliver(_ notice: PlayerNotice, to rig: CoordinatorRig) {
  rig.bridge.post(notice)
  rig.scheduler.advance(by: Debouncer.window)
}

/// A rig whose permission request is held, started with Music playing track one.
@MainActor private func rigWithAHeldRequest() throws -> CoordinatorRig {
  let rig = try CoordinatorRig()
  rig.bridge.permission = nil
  rig.bridge.snapshot = .success(snapshot())
  rig.playing(0)
  rig.coordinator.start()
  return rig
}

/// How many position polls are scheduled.
@MainActor private func polls(_ rig: CoordinatorRig) -> Int {
  rig.scheduler.repeatingJobs(every: Engine.pollInterval).count
}

@MainActor @Test func anUnansweredRequestIsInTheStatusFileAtOnce() throws {
  let rig = try rigWithAHeldRequest()
  // `start` ends by writing the file, which is what put the time there; the next test
  // pins the write a request makes on its own.
  #expect(try rig.status()["automation_asked_at"] as? Double == base)
}

@MainActor @Test func aRequestMadeAfterStartIsInTheStatusFileAtOnce() throws {
  // Music is not running at start, so nothing is asked until its first notice.
  let rig = try CoordinatorRig()
  rig.bridge.running = false
  rig.coordinator.start()
  rig.bridge.running = true
  rig.bridge.permission = nil
  rig.scheduler.advance(by: 3)
  deliver(notice(.playing), to: rig)
  #expect(rig.bridge.count("permission") == 1)
  // No heartbeat has run since: the request's start is what wrote the file.
  #expect(try rig.status()["automation_asked_at"] as? Double == rig.scheduler.now)
}

@MainActor @Test func aRequestAnsweredAtOnceLeavesNoPendingTimeOnDisk() throws {
  let rig = try CoordinatorRig()
  rig.playing(0)
  rig.coordinator.start()
  #expect(try rig.status()["automation_asked_at"] is NSNull)
}

@MainActor @Test func anAnswerClearsThePendingTimeOnDiskAtOnce() throws {
  let rig = try rigWithAHeldRequest()
  rig.scheduler.advance(by: 5)
  rig.bridge.answerPermission(.denied)
  // Still no heartbeat: the answer's arrival wrote the file, the denial with it.
  let status = try rig.status()
  #expect(status["automation_asked_at"] is NSNull)
  #expect(status["automation_denied"] as? Bool == true)
}

@MainActor @Test func musicQuittingAbandonsTheRequestSoTheNextNoticeAsksAnew() throws {
  let rig = try rigWithAHeldRequest()
  rig.bridge.quit()
  #expect(try rig.status()["automation_asked_at"] is NSNull)
  rig.bridge.running = true
  deliver(notice(.playing), to: rig)
  #expect(rig.bridge.count("permission") == 2)
  // The abandoned request's answer, arriving at last, is dropped: no denial is reported.
  rig.bridge.answerPermission(.denied)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["automation_denied"] as? Bool == false)
  #expect(rig.bridge.count("snapshot") == 0)
  // The request made anew is the one whose answer counts.
  rig.bridge.answerPermission(.granted)
  #expect(rig.bridge.count("snapshot") == 1)
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.snapshot == snapshot())
}

/// When the status file was last written: the clock moves on between writes, so a time
/// that has not moved means no write was made.
@MainActor private func writtenAt(_ rig: CoordinatorRig) throws -> Double? {
  try rig.status()["heartbeat_at"] as? Double
}

/// A rig playing track one whose every request so far was answered `answer` at once, and
/// whose later requests are held, as the live bridge answers: after the ask returns.
@MainActor private func rigPlaying(answering answer: AutomationPermission) throws
  -> CoordinatorRig
{
  let rig = try CoordinatorRig()
  rig.bridge.permission = answer
  rig.playing(0)
  rig.coordinator.start()
  deliver(notice(.playing), to: rig)
  rig.bridge.permission = nil
  return rig
}

// A denial already decided and a failed request each answer with no prompt, and each is
// asked again at every poll for as long as it lasts.
@MainActor @Test(arguments: [AutomationPermission.denied, .other(-1)])
func anAnswerRepeatedAtEachPollWritesNoStatus(_ answer: AutomationPermission) throws {
  let rig = try rigPlaying(answering: answer)
  let asked = rig.bridge.count("permission")
  let written = try writtenAt(rig)
  for _ in 1...5 {
    rig.scheduler.advance(by: Engine.pollInterval)
    rig.bridge.answerPermission(answer)
  }
  #expect(rig.bridge.count("permission") == asked + 5)
  #expect(try writtenAt(rig) == written)
}

@MainActor @Test func aRequestAfterADenialThatHangsIsOnDiskAtTheNextHeartbeat() throws {
  let rig = try rigPlaying(answering: .denied)
  rig.scheduler.advance(by: Engine.pollInterval)
  let askedAt = rig.scheduler.now
  #expect(try rig.status()["automation_asked_at"] is NSNull)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try rig.status()["automation_asked_at"] as? Double == askedAt)
  // The pending time reached the file, so the answer clears it there at once.
  rig.bridge.answerPermission(.denied)
  #expect(try rig.status()["automation_asked_at"] is NSNull)
  #expect(try writtenAt(rig) == rig.scheduler.now)
}

@MainActor @Test func aPendingTimeWhoseWriteFailedIsStillClearedByTheAnswer() throws {
  let rig = try rigPlaying(answering: .denied)
  rig.scheduler.advance(by: Engine.pollInterval)
  // The heartbeat's write, the one carrying the pending time, fails. A write can fail
  // after its rename too, so the time has to be taken as on disk from then on.
  let stateDir = rig.state.statusFile.deletingLastPathComponent()
  try setMode(0o500, of: stateDir)
  defer { try? setMode(0o700, of: stateDir) }
  let written = try writtenAt(rig)
  rig.scheduler.advance(by: Engine.heartbeatInterval)
  #expect(try writtenAt(rig) == written)
  try setMode(0o700, of: stateDir)
  // The answer changes no denial, yet it writes: there may be a pending time to clear.
  rig.bridge.answerPermission(.denied)
  #expect(try rig.status()["automation_asked_at"] is NSNull)
  #expect(try writtenAt(rig) == rig.scheduler.now)
}

@MainActor @Test func aDenialLiftedIsInTheStatusFileAtOnce() throws {
  let rig = try rigPlaying(answering: .denied)
  rig.scheduler.advance(by: Engine.pollInterval)
  rig.bridge.answerPermission(.granted)
  let status = try rig.status()
  #expect(status["automation_denied"] as? Bool == false)
  #expect(status["heartbeat_at"] as? Double == rig.scheduler.now)
}

@MainActor @Test func aLateNotRunningAnswerAfterASeenQuitLeavesTheNewPlayPolling() throws {
  let rig = try rigWithAHeldRequest()
  rig.bridge.quit()
  rig.bridge.running = true
  deliver(notice(.playing), to: rig)
  #expect(polls(rig) == 1)
  rig.bridge.answerPermission(.musicNotRunning)
  #expect(polls(rig) == 1)
  #expect(rig.activity.last == true)
}

@MainActor @Test func aNotRunningAnswerWhileMusicRunsIsStaleAndAskedAgain() throws {
  // Music quit and came back without the quit being seen, so the request is still the
  // current one when its "not running" answer arrives.
  let rig = try rigWithAHeldRequest()
  deliver(notice(.playing), to: rig)
  rig.bridge.answerPermission(.musicNotRunning)
  #expect(polls(rig) == 1)
  #expect(rig.bridge.count("permission") == 1)
  rig.scheduler.advance(by: Engine.pollInterval)
  #expect(rig.bridge.count("permission") == 2)
  // This request is the one most likely to raise the prompt, so its time is on disk at
  // once, with no heartbeat run since.
  #expect(try rig.status()["automation_asked_at"] as? Double == rig.scheduler.now)
  rig.bridge.answerPermission(.granted)
  #expect(rig.bridge.count("snapshot") == 1)
  #expect(rig.state.readOpenPlay(OpenPlay.self)?.snapshot == snapshot())
}

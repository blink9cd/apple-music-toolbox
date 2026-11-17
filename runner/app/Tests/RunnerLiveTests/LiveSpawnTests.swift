import Foundation
import RunnerCore
import Testing

@testable import RunnerLive

/// Whether the live switch is on. Every test here starts a real process, so each one is
/// disabled unless `RUNNER_LIVE` is "1". They start only /usr/bin/true and /bin/sh: no
/// bundle, no self-check, no Music.app. Each disarms its spawner's forwarder afterward, so
/// the test process's signal dispositions are restored before the next test.
let liveSwitchOn = ProcessInfo.processInfo.environment["RUNNER_LIVE"] == "1"

/// Spawn `argv` with a fresh live spawner, wait, and map the status as the runner does.
func runLive(_ argv: [String]) throws -> Int32 {
  let spawner = PosixSpawner()
  defer { spawner.forwarder.disarm() }
  let pid = try spawner.spawn(argv)
  return ExitStatus.code(waitStatus: spawner.wait(pid))
}

@Suite(.serialized) struct LiveSpawnTests {
  /// How long the forwarding test's child would run if the signal never reached it.
  static let childSeconds = 5.0
  /// Well under `childSeconds`: the forwarded SIGTERM must end the child early.
  static let forwardedWithin = 3.0

  @Test(.enabled(if: liveSwitchOn))
  func aChildThatSucceedsExitsZero() throws {
    #expect(try runLive(["/usr/bin/true"]) == 0)
  }

  @Test(.enabled(if: liveSwitchOn))
  func aChildsOwnCodeIsReturned() throws {
    #expect(try runLive(["/bin/sh", "-c", "exit 3"]) == 3)
  }

  @Test(.enabled(if: liveSwitchOn))
  func aChildKilledBySigtermIs143() throws {
    // A spawn first, so this process has already had SIGTERM ignored once: the child must
    // still get the default action rather than inherit an ignore.
    #expect(try runLive(["/usr/bin/true"]) == 0)
    #expect(try runLive(["/bin/sh", "-c", "kill -TERM $$"]) == 143)
  }

  @Test(.enabled(if: liveSwitchOn))
  func aMissingProgramIsASpawnFailure() {
    #expect(throws: RunnerError.spawnFailed(ENOENT)) {
      try runLive(["/nonexistent/runner-live-probe"])
    }
  }

  @Test(.enabled(if: liveSwitchOn))
  func aSigtermToTheRunnerIsForwardedToTheChild() throws {
    let spawner = PosixSpawner()
    defer { spawner.forwarder.disarm() }
    let pid = try spawner.spawn(["/bin/sh", "-c", "sleep \(Int(Self.childSeconds))"])
    let started = Date()
    // To this (the runner's) process: armed, it is ignored here and relayed to the child.
    kill(getpid(), SIGTERM)
    let code = ExitStatus.code(waitStatus: spawner.wait(pid))
    #expect(code == 143)
    #expect(Date().timeIntervalSince(started) < Self.forwardedWithin)
  }

  @Test(.enabled(if: liveSwitchOn))
  func aSignalBeforeTheChildExistsIsHeldAndDelivered() async throws {
    // The window between arming and the spawn: a SIGHUP then must neither end this process
    // nor be lost, but reach the child once it is targeted.
    let early = SignalForwarder()
    defer { early.disarm() }
    #expect(early.arm([SIGHUP]))
    kill(getpid(), SIGHUP)
    let deadline = Date().addingTimeInterval(Self.forwardedWithin)
    while early.pendingSignals.isEmpty && Date() < deadline {
      try await Task.sleep(for: .milliseconds(10))
    }
    #expect(early.pendingSignals == [SIGHUP])
    let spawner = PosixSpawner()
    defer { spawner.forwarder.disarm() }
    let pid = try spawner.spawn(["/bin/sh", "-c", "sleep \(Int(Self.childSeconds))"])
    early.target(pid)
    #expect(ExitStatus.code(waitStatus: spawner.wait(pid)) == 128 + SIGHUP)
    #expect(early.pendingSignals.isEmpty)
  }

  @Test(.enabled(if: liveSwitchOn))
  func aSignalThatCannotBeIgnoredFailsTheArm() {
    // The kernel refuses to ignore SIGKILL, so `signal` returns SIG_ERR; nothing is sent.
    let forwarder = SignalForwarder()
    defer { forwarder.disarm() }
    #expect(!forwarder.arm([SIGKILL]))
  }

  @Test
  func onlySigErrReadsAsAFailedSignalCall() {
    // Pure: no process is started and no disposition is changed.
    #expect(SignalForwarder.isError(SIG_ERR))
    #expect(!SignalForwarder.isError(SIG_IGN))
    #expect(!SignalForwarder.isError(SIG_DFL))
  }

  @Test(.enabled(if: liveSwitchOn))
  func aFailedWaitIsNeverSuccess() {
    // This process is not its own child, so waitpid fails with ECHILD.
    #expect(ExitStatus.code(waitStatus: PosixSpawner().wait(getpid())) == 1)
  }
}

import Testing

@testable import RunnerCore

/// The command line most supervisor tests run.
let goodCall = ["--python", "/v/p", "--script", "/r/a.py", "--", "x"]

/// The allowlist that admits `goodCall`.
func goodList() -> Allowlist? {
  Allowlist(python: "/v/p", scripts: ["/r/a.py"])
}

@Test func supervisorSpawnsChildAndReturnsItsCode() throws {
  let fake = FakeSpawner(waitStatus: 3 << 8)
  let code = Supervisor.run(
    arguments: ["--python", "/v/p", "--script", "/r/a.py", "--", "x"],
    allowlist: { Allowlist(python: "/v/p", scripts: ["/r/a.py"]) },
    selfCheck: { true }, spawner: fake, report: { _ in })
  #expect(code == 3)
  #expect(fake.spawned == [["/v/p", "/r/a.py", "x"]])
}

@Test func waitsOnThePidItSpawnedAndReportsNothingOnSuccess() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  let code = Supervisor.run(
    arguments: goodCall, allowlist: goodList, selfCheck: { true }, spawner: fake,
    report: log.add)
  #expect(code == 0)
  #expect(fake.waited == [FakeSpawner.pid])
  #expect(log.lines.isEmpty)
}

@Test func aSignalDeathIsReturnedAs128PlusTheSignal() {
  let fake = FakeSpawner(waitStatus: 15)
  let code = Supervisor.run(
    arguments: goodCall, allowlist: goodList, selfCheck: { true }, spawner: fake,
    report: { _ in })
  #expect(code == 143)
}

@Test func aBadCommandLineIsRefusedBeforeTheSelfCheck() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  var checked = false
  let code = Supervisor.run(
    arguments: ["--python", "/v/p"], allowlist: goodList,
    selfCheck: {
      checked = true
      return true
    }, spawner: fake, report: log.add)
  #expect(code == 2)
  #expect(!checked)
  #expect(fake.spawned.isEmpty)
  #expect(log.lines == ["ERROR: --script is required"])
}

@Test func aFailedSelfCheckIsRefusedWithoutReadingTheAllowlist() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  var read = false
  let code = Supervisor.run(
    arguments: goodCall,
    allowlist: {
      read = true
      return goodList()
    }, selfCheck: { false }, spawner: fake, report: log.add)
  #expect(code == 2)
  #expect(!read)
  #expect(fake.spawned.isEmpty)
  #expect(log.lines == ["ERROR: the runner's own signature does not verify"])
}

@Test func anUnreadableAllowlistIsRefused() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  let code = Supervisor.run(
    arguments: goodCall, allowlist: { nil }, selfCheck: { true }, spawner: fake,
    report: log.add)
  #expect(code == 2)
  #expect(fake.spawned.isEmpty)
  #expect(log.lines == ["ERROR: the runner's allowlist is missing or malformed"])
}

@Test func aScriptNotAllowedIsRefused() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  let code = Supervisor.run(
    arguments: ["--python", "/v/p", "--script", "/r/b.py", "--"], allowlist: goodList,
    selfCheck: { true }, spawner: fake, report: log.add)
  #expect(code == 2)
  #expect(fake.spawned.isEmpty)
  #expect(log.lines == ["ERROR: not in the runner's allowlist: /r/b.py"])
}

@Test func anInterpreterNotAllowedIsRefused() {
  let fake = FakeSpawner(waitStatus: 0)
  let log = ReportLog()
  let code = Supervisor.run(
    arguments: ["--python", "/v/q", "--script", "/r/a.py", "--"], allowlist: goodList,
    selfCheck: { true }, spawner: fake, report: log.add)
  #expect(code == 2)
  #expect(fake.spawned.isEmpty)
  #expect(log.lines == ["ERROR: not in the runner's allowlist: /v/q"])
}

@Test func aSpawnErrorExitsOne() {
  // 2 is ENOENT on every Darwin release.
  let fake = FakeSpawner(waitStatus: 0, failure: .spawnFailed(2))
  let log = ReportLog()
  let code = Supervisor.run(
    arguments: goodCall, allowlist: goodList, selfCheck: { true }, spawner: fake,
    report: log.add)
  #expect(code == 1)
  #expect(fake.waited.isEmpty)
  #expect(log.lines == ["ERROR: could not start the child: No such file or directory (errno 2)"])
}

@Test func eachRefusalExitsTwoAndOnlyASpawnFailureExitsOne() {
  #expect(RunnerError.usage("x").exitCode == 2)
  #expect(RunnerError.notAllowed("/x").exitCode == 2)
  #expect(RunnerError.selfCheckFailed.exitCode == 2)
  #expect(RunnerError.allowlistUnreadable.exitCode == 2)
  #expect(RunnerError.spawnFailed(2).exitCode == 1)
}

import Testing

@testable import RunnerCore

@Test func signalDeathMapsTo128PlusSignal() {
  #expect(ExitStatus.code(waitStatus: 15) == 143)  // SIGTERM, no core
  #expect(ExitStatus.code(waitStatus: 3 << 8) == 3)
}

@Test func aCoreDumpKeepsTheSignalNumber() {
  // 0x80 is the core-dumped bit; the signal is the low seven bits (SIGABRT here).
  #expect(ExitStatus.code(waitStatus: 0x80 | 6) == 134)
}

@Test func aCleanExitIsZeroAndTheTopCodeSurvives() {
  #expect(ExitStatus.code(waitStatus: 0) == 0)
  #expect(ExitStatus.code(waitStatus: 255 << 8) == 255)
}

@Test func aStoppedChildIsAFailure() {
  // Low bits 0x7f mean stopped, with the stopping signal above them (SIGSTOP here).
  #expect(ExitStatus.code(waitStatus: (17 << 8) | 0x7f) == 1)
}

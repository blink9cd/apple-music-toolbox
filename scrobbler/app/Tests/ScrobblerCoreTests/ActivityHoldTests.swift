import Testing

@testable import ScrobblerCore

/// The hold on App Nap: one begun while a track plays, ended when it stops.
@MainActor @Suite struct ActivityHoldTests {
  /// A hold whose begin and end calls are recorded, each begin handing out the next number.
  @MainActor final class Recorder {
    var begun: [Int] = []
    var ended: [Int] = []

    func hold() -> ActivityHold<Int> {
      ActivityHold(
        begin: { [unowned self] in
          begun.append(begun.count + 1)
          return begun.count
        }, end: { [unowned self] in ended.append($0) })
    }
  }

  @Test func playingBeginsOneHoldHoweverOftenItIsSaid() {
    let recorder = Recorder()
    let hold = recorder.hold()
    hold.set(true)
    hold.set(true)
    #expect(recorder.begun == [1])
    #expect(recorder.ended.isEmpty)
    #expect(hold.isHeld)
  }

  @Test func stoppingEndsTheHoldItBegan() {
    let recorder = Recorder()
    let hold = recorder.hold()
    hold.set(true)
    hold.set(false)
    hold.set(false)
    #expect(recorder.ended == [1])
    #expect(!hold.isHeld)
  }

  @Test func stoppingWithoutAHoldEndsNothing() {
    let recorder = Recorder()
    let hold = recorder.hold()
    hold.set(false)
    #expect(recorder.begun.isEmpty)
    #expect(recorder.ended.isEmpty)
  }

  @Test func theNextPlayBeginsAFreshHold() {
    let recorder = Recorder()
    let hold = recorder.hold()
    hold.set(true)
    hold.set(false)
    hold.set(true)
    #expect(recorder.begun == [1, 2])
    #expect(recorder.ended == [1])
  }
}

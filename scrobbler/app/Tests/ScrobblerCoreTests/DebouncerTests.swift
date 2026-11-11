import Foundation
import Testing

@testable import ScrobblerCore

@Test func twoNoticesInsideTheWindowFireOnceAsTheNewer() {
  var debouncer = Debouncer()
  let first = debouncer.offer(notice(.paused), at: 10)
  #expect(first == 10 + Debouncer.window)
  let second = debouncer.offer(notice(.playing), at: 10.025)
  #expect(second == 10.025 + Debouncer.window)
  // The first deadline has been pushed back, so its timer finds nothing to fire.
  #expect(debouncer.fire(at: first) == nil)
  #expect(debouncer.fire(at: second) == notice(.playing))
  #expect(debouncer.fire(at: second + 1) == nil)
}

@Test func aNoticeAfterTheWindowStartsANewWindow() {
  var debouncer = Debouncer()
  let first = debouncer.offer(notice(.playing), at: 10)
  #expect(debouncer.fire(at: first) == notice(.playing))
  let second = debouncer.offer(notice(.paused), at: 11)
  #expect(second == 11 + Debouncer.window)
  #expect(debouncer.fire(at: second) == notice(.paused))
}

@Test func firingBeforeTheDeadlineReturnsNothing() {
  var debouncer = Debouncer()
  let deadline = debouncer.offer(notice(.playing), at: 10)
  #expect(debouncer.fire(at: deadline - 0.01) == nil)
  #expect(debouncer.fire(at: deadline) == notice(.playing))
}

@Test func firingWithNothingOfferedReturnsNothing() {
  var debouncer = Debouncer()
  #expect(debouncer.fire(at: 10) == nil)
  #expect(Debouncer.window == 0.25)
}

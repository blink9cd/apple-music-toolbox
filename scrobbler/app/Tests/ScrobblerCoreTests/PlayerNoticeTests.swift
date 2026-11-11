import Foundation
import Testing

@testable import ScrobblerCore

@Test func noticeParsesTheFieldsAPlayerInfoNoticeCarries() {
  let notice = PlayerNotice.parse([
    "Player State": "Playing", "Persistent ID": "0A1B2C3D4E5F6071",
    "Name": "Harbor Lights at Noon", "Artist": "The Paper Lanterns",
    "Album": "Saltwater Almanac", "Total Time": 214000,
  ])
  #expect(notice?.state == .playing)
  #expect(notice?.totalTimeMs == 214000)
  #expect(PlayerNotice.parse(["Player State": "Rewinding"]) == nil)
}

@Test func noticeKeepsEveryField() {
  let notice = PlayerNotice.parse([
    "Player State": "Paused", "Persistent ID": NSNumber(value: Int64(0x0A1B_2C3D_4E5F_6071)),
    "Name": "Harbor Lights at Noon", "Artist": "The Paper Lanterns",
    "Album": "Saltwater Almanac", "Total Time": NSNumber(value: 214000),
  ])
  #expect(
    notice
      == PlayerNotice(
        state: .paused, persistentID: "0A1B2C3D4E5F6071", name: "Harbor Lights at Noon",
        artist: "The Paper Lanterns", album: "Saltwater Almanac", totalTimeMs: 214000))
}

@Test func stoppedNoticeNeedsOnlyTheState() {
  #expect(
    PlayerNotice.parse(["Player State": "Stopped"])
      == PlayerNotice(
        state: .stopped, persistentID: nil, name: nil, artist: nil, album: nil, totalTimeMs: nil))
}

@Test func missingOrNonTextStateIsNoNotice() {
  #expect(PlayerNotice.parse([:]) == nil)
  #expect(PlayerNotice.parse(["Player State": 1]) == nil)
  #expect(PlayerNotice.parse(["Name": "Harbor Lights at Noon"]) == nil)
}

@Test func wronglyTypedFieldsAreDropped() {
  let notice = PlayerNotice.parse([
    "Player State": "Playing", "Persistent ID": "not hex", "Name": 7, "Artist": ["x"],
    "Album": NSNull(), "Total Time": "214000",
  ])
  #expect(
    notice
      == PlayerNotice(
        state: .playing, persistentID: nil, name: nil, artist: nil, album: nil, totalTimeMs: nil))
}

@Test func negativeOrFractionalTotalTimeIsDropped() {
  #expect(PlayerNotice.parse(["Player State": "Playing", "Total Time": -1])?.totalTimeMs == nil)
  #expect(PlayerNotice.parse(["Player State": "Playing", "Total Time": 1.5])?.totalTimeMs == nil)
  #expect(PlayerNotice.parse(["Player State": "Playing", "Total Time": 0])?.totalTimeMs == 0)
}

@Test func aNoticeTextFieldOverTheCapIsDropped() {
  let huge = String(repeating: "a", count: 1 << 20)
  let notice = PlayerNotice.parse([
    "Player State": "Playing", "Name": huge, "Artist": huge, "Album": huge,
  ])
  #expect(notice?.name == nil)
  #expect(notice?.artist == nil)
  #expect(notice?.album == nil)
}

@Test func aNoticeTextFieldAtTheCapIsKept() {
  // Two bytes a letter, so the cap is counted in UTF-8 bytes, not characters.
  let atCap = String(repeating: "\u{E9}", count: FieldText.maxTextBytes / 2)
  let notice = PlayerNotice.parse(["Player State": "Playing", "Name": atCap, "Album": atCap + "a"])
  #expect(notice?.name == atCap)
  #expect(notice?.album == nil)
}

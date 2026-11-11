import Foundation
import Testing

@testable import ScrobblerCore

@Test func noticeNumberAndStringPersistentIDsNormalizeAlike() {
  #expect(
    PersistentID.normalize(NSNumber(value: Int64(bitPattern: 0x0A1B_2C3D_4E5F_6071)))
      == "0A1B2C3D4E5F6071")
  #expect(PersistentID.normalize("a1b2c3d4e5f60718") == "A1B2C3D4E5F60718")
  #expect(PersistentID.normalize(NSNumber(value: Int64(-1))) == "FFFFFFFFFFFFFFFF")
  #expect(PersistentID.normalize("not hex") == nil)
  #expect(PersistentID.normalize(nil) == nil)
}

@Test func shortHexStringsArePaddedOnTheLeft() {
  #expect(PersistentID.normalize("abc") == "0000000000000ABC")
  #expect(PersistentID.normalize("0") == "0000000000000000")
}

@Test func emptyOverlongAndNonAsciiHexStringsAreRejected() {
  #expect(PersistentID.normalize("") == nil)
  #expect(PersistentID.normalize("0A1B2C3D4E5F60718") == nil)
  // Fullwidth digits count as hex digits to Character.isHexDigit, never to a persistent ID.
  #expect(PersistentID.normalize("\u{FF10}\u{FF11}") == nil)
  #expect(PersistentID.normalize(" 0A1B") == nil)
}

@Test func swiftIntegersAndUnsignedNumbersUseTheirBitPattern() {
  #expect(PersistentID.normalize(255) == "00000000000000FF")
  #expect(PersistentID.normalize(NSNumber(value: UInt64.max)) == "FFFFFFFFFFFFFFFF")
}

@Test func booleansAndOtherValuesAreNotPersistentIDs() {
  #expect(PersistentID.normalize(true) == nil)
  #expect(PersistentID.normalize(NSNumber(value: false)) == nil)
  #expect(PersistentID.normalize(["0A1B"]) == nil)
  #expect(PersistentID.normalize(Data([1, 2])) == nil)
}

@Test func fractionalNumbersAreNotPersistentIDs() {
  #expect(PersistentID.normalize(NSNumber(value: 1.5)) == nil)
  #expect(PersistentID.normalize(1.5) == nil)
  #expect(PersistentID.normalize(NSNumber(value: Float(2))) == nil)
}

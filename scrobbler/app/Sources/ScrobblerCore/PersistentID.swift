import Foundation

/// Music's persistent ID in the one spelling the scrobbler compares: 16 uppercase hex digits.
///
/// A playerInfo notice carries the ID as a number, while AppleScript returns it as text, so
/// both forms are folded into one string here before any two IDs are compared.
public enum PersistentID {
  /// The number of hex digits a 64-bit ID spells out.
  static let digitCount = 16

  /// A string is uppercased and must be 1 to 16 hex digits, left-padded to 16; a number
  /// is its unsigned 64-bit pattern as 16 uppercase hex digits. Anything else is nil.
  public static func normalize(_ value: Any?) -> String? {
    if let text = value as? String {
      return normalize(text: text)
    }
    // A Bool bridges to NSNumber too, but a flag is never an ID, and neither is a
    // floating-point number such as 1.5.
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
      !CFNumberIsFloatType(number)
    else {
      return nil
    }
    return padded(String(UInt64(bitPattern: number.int64Value), radix: 16, uppercase: true))
  }

  /// The text form: ASCII hex only, since `Character.isHexDigit` also admits fullwidth digits.
  private static func normalize(text: String) -> String? {
    let upper = text.uppercased()
    let scalars = upper.unicodeScalars
    guard scalars.allSatisfy(isHexDigit), (1...digitCount).contains(scalars.count) else {
      return nil
    }
    return padded(upper)
  }

  /// Whether a scalar is an ASCII digit or an uppercase ASCII letter A to F.
  private static func isHexDigit(_ scalar: Unicode.Scalar) -> Bool {
    ("0"..."9").contains(scalar) || ("A"..."F").contains(scalar)
  }

  /// Left-pads hex digits with zeros to the full width.
  private static func padded(_ hex: String) -> String {
    String(repeating: "0", count: digitCount - hex.count) + hex
  }
}

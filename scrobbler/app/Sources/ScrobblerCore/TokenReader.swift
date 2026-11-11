import Foundation

/// Why the store's token file was not read. No case carries any of the file's content, so
/// an error can be logged or written to `status.json` without leaking the token.
public enum TokenError: Error, Equatable, Sendable {
  /// No file at the path.
  case missing
  /// A symlink, a folder or anything else that is not a regular file.
  case notRegularFile
  /// The file belongs to another user.
  case wrongOwner
  /// A group or other user may read or write the file.
  case tooOpen
  /// Larger than any token file.
  case tooLarge
  /// Not 64 lowercase hex characters and at most one trailing newline.
  case malformed
  /// The file could not be opened for some other reason.
  case unreadable
}

/// Reads the store's write token, trusting the file only when it is safe to.
///
/// The same rules as the store's own reader: the file is opened without following a
/// symlink and without blocking on a FIFO, then the open descriptor itself is checked, so
/// the file checked is the file read. Nothing here caches the token.
public enum TokenReader {
  /// The largest file read. A token file is 65 bytes; a bigger file is not one.
  public static let maxFileBytes = 4096
  /// The token's length: 32 bytes as hex.
  static let tokenLength = 64
  /// Read only, never through a symlink, never blocking on a FIFO planted at the path.
  static let openFlags = O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC
  /// The bytes a token may hold.
  private static let lowercaseHex = Set("0123456789abcdef".utf8)

  /// The token in the file at `url`, refused unless it is a regular file, belongs to
  /// `uid`, is private, and holds exactly one token.
  public static func read(at url: URL, uid: uid_t) throws(TokenError) -> String {
    let descriptor = open(url.path, openFlags)
    guard descriptor >= 0 else { throw openError(errno) }
    defer { close(descriptor) }
    if let refusal = refusal(of: FileIO.status(of: descriptor), uid: uid) { throw refusal }
    // One byte past the cap tells a file over it from one exactly at it.
    let data = FileIO.readBytes(descriptor, upTo: maxFileBytes + 1)
    guard data.count <= maxFileBytes else { throw .tooLarge }
    guard let token = tokenText(data) else { throw .malformed }
    return token
  }

  /// The refusal an `open` failure with `code` means. A symlink fails with `ELOOP` under
  /// `O_NOFOLLOW`, so it reads as not a regular file.
  static func openError(_ code: Int32) -> TokenError {
    switch code {
    case ENOENT: .missing
    case ELOOP: .notRegularFile
    default: .unreadable
    }
  }

  /// The rule an open file with status `info` breaks for `uid`, or nil when it may be read.
  static func refusal(of info: stat, uid: uid_t) -> TokenError? {
    if !FileIO.isRegularFile(info) { return .notRegularFile }
    if info.st_uid != uid { return .wrongOwner }
    if info.st_mode & FileIO.groupOrOther != 0 { return .tooOpen }
    return nil
  }

  /// The token `data` holds: exactly 64 lowercase hex characters and at most one trailing
  /// newline; nil for anything else.
  static func tokenText(_ data: Data) -> String? {
    let body = data.last == UInt8(ascii: "\n") ? data.dropLast() : data
    guard body.count == tokenLength, body.allSatisfy(lowercaseHex.contains) else { return nil }
    return String(bytes: body, encoding: .ascii)
  }
}

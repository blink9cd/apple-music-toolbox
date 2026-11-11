import Foundation

/// A POSIX call that failed: which call, and the `errno` it left. It names no path and
/// holds no file content, so it is safe to log.
public struct FileIOError: Error, Equatable, Sendable {
  /// The call that failed, such as `open` or `rename`.
  public let call: String
  /// The `errno` the call left.
  public let code: Int32
}

/// The small file primitives the queue, the state files, the config and the token share.
enum FileIO {
  /// Files the scrobbler writes are readable by their user only: a listen is personal.
  static let privateFileMode: mode_t = 0o600
  /// Folders the scrobbler makes, for the same reason.
  static let privateFolderMode = 0o700
  /// The prefix of a file being written; nothing that reads a folder takes it for a record.
  static let tempPrefix = ".tmp-"
  /// How many bytes one `read` call asks for.
  private static let readChunk = 4096

  /// `result` when it is not negative; otherwise a `FileIOError` for `call` and `errno`.
  @discardableResult
  static func check<T: BinaryInteger>(_ result: T, _ call: String) throws(FileIOError) -> T {
    guard result >= 0 else { throw FileIOError(call: call, code: errno) }
    return result
  }

  /// Make `folder` and its parents, each new one private.
  static func makeFolder(_ folder: URL) throws {
    try FileManager.default.createDirectory(
      at: folder, withIntermediateDirectories: true,
      attributes: [.posixPermissions: privateFolderMode])
  }

  /// Replace `url` with `data` so a reader sees the old file or the new one, never part of
  /// either: a private temp file beside it, written and flushed to disk, then renamed over
  /// it, then the folder flushed so the rename itself survives a power cut. The folder must
  /// be private to this user, so no one else can plant or swap a file in it.
  static func writeAtomically(_ data: Data, to url: URL) throws {
    let folder = url.deletingLastPathComponent()
    try makeFolder(folder)
    let folderDescriptor = try openPrivateFolder(folder)
    defer { close(folderDescriptor) }
    let temp = folder.appendingPathComponent(tempPrefix + UUID().uuidString)
    let flags = O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC
    let descriptor = try check(open(temp.path, flags, privateFileMode), "open")
    var renamed = false
    // A failure at any step below removes the temp file, so no partial write is left.
    defer { if !renamed { unlink(temp.path) } }
    do {
      defer { close(descriptor) }
      try writeAll(data, to: descriptor)
      try check(fsync(descriptor), "fsync")
    }
    try check(rename(temp.path, url.path), "rename")
    renamed = true
    try check(fsync(folderDescriptor), "fsync folder")
  }

  /// Write every byte of `data`; `write` may take fewer than it was given.
  private static func writeAll(_ data: Data, to descriptor: Int32) throws {
    try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) throws in
      var offset = 0
      while offset < raw.count {
        let start = raw.baseAddress.map { $0 + offset }
        offset += try check(write(descriptor, start, raw.count - offset), "write")
      }
    }
  }

  /// `folder` opened, refused unless it is a real folder, not a symlink, belonging to this
  /// user, and closed to every other user. Every folder the scrobbler makes is mode 0700.
  static func openPrivateFolder(_ folder: URL) throws(FileIOError) -> Int32 {
    let flags = O_RDONLY | O_NOFOLLOW | O_DIRECTORY | O_CLOEXEC
    let descriptor = try check(open(folder.path, flags), "open folder")
    let info = status(of: descriptor)
    guard info.st_uid == getuid(), info.st_mode & groupOrOther == 0 else {
      close(descriptor)
      throw FileIOError(call: "folder check", code: EPERM)
    }
    return descriptor
  }

  /// The permission bits a group or other user reaches a file or folder through.
  static let groupOrOther: mode_t = 0o077

  /// The bytes of the regular file at `url`, read only when it is at most `limit` bytes.
  ///
  /// Never through a symlink and never blocking on a FIFO: the open does not follow a
  /// symlink and does not wait, and the open descriptor itself must be a regular file.
  static func readRegularFile(_ url: URL, limit: Int) throws(FileIOError) -> Data {
    let flags = O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC
    let descriptor = try check(open(url.path, flags), "open")
    defer { close(descriptor) }
    guard isRegularFile(status(of: descriptor)) else {
      throw FileIOError(call: "fstat", code: EFTYPE)
    }
    // One byte past the cap tells a file over it from one exactly at it.
    let data = readBytes(descriptor, upTo: limit + 1)
    guard data.count <= limit else { throw FileIOError(call: "read", code: EFBIG) }
    return data
  }

  /// Delete the file at `url`; one already gone is fine, and a folder is never removed.
  static func unlinkIfPresent(_ url: URL) throws(FileIOError) {
    if unlink(url.path) != 0 && errno != ENOENT {
      throw FileIOError(call: "unlink", code: errno)
    }
  }

  /// Whether the entry at `url`, not following a symlink, is a folder.
  static func isFolderEntry(_ url: URL) -> Bool {
    var info = stat()
    // A failed lstat leaves a zero mode, which is not a folder: the entry is then listed
    // and its read reports it, rather than it vanishing from the queue unseen.
    _ = lstat(url.path, &info)
    return info.st_mode & S_IFMT == S_IFDIR
  }

  /// The status of the open `descriptor`.
  ///
  /// A failed `fstat` leaves the result zeroed, and a zero mode is not a regular file, so
  /// every caller's regular-file check refuses it without a branch of its own.
  static func status(of descriptor: Int32) -> stat {
    var info = stat()
    _ = fstat(descriptor, &info)
    return info
  }

  /// Whether `info` describes a regular file.
  static func isRegularFile(_ info: stat) -> Bool {
    info.st_mode & S_IFMT == S_IFREG
  }

  /// At most `limit` bytes from `descriptor`, stopping at the end of the file.
  ///
  /// A read error ends the read like the end of the file: every caller judges the bytes it
  /// got, and a short read is never a well-formed token or config object.
  static func readBytes(_ descriptor: Int32, upTo limit: Int) -> Data {
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: readChunk)
    while data.count < limit {
      let count = read(descriptor, &buffer, min(buffer.count, limit - data.count))
      if count <= 0 { break }
      data.append(buffer, count: count)
    }
    return data
  }
}

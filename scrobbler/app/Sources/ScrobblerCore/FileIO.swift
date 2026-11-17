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

  /// Make `folder` and its missing parents, each new one private (`openMadeFolder`).
  ///
  /// `owned`, the folder itself when nil, is the highest level the scrobbler treats as its
  /// own: from it down, a link is refused.
  static func makeFolder(_ folder: URL, owning owned: URL? = nil) throws(FileIOError) {
    close(try openMadeFolder(folder, owning: owned ?? folder))
  }

  /// `folder`, made with each missing parent and returned open.
  ///
  /// `owned` is `folder` or a folder above it, and the levels above `owned` are the user's
  /// own (the home folder, `Library`): those that exist are used as found, a link among
  /// them included. Every level from `owned` down to `folder`, and any missing level above
  /// `owned`, is made and opened inside the one above it without following a link
  /// (`openLevel`), so a link at any of those levels, planted before or swapped in during
  /// the walk, is refused. Both must be standardized absolute paths (`missingLevels`).
  static func openMadeFolder(_ folder: URL, owning owned: URL) throws(FileIOError) -> Int32 {
    let (base, names) = try missingLevels(of: folder, owning: owned)
    var descriptor = try check(open(base.path, O_RDONLY | O_DIRECTORY | O_CLOEXEC), "open folder")
    for name in names {
      let parent = descriptor
      // The walk holds one descriptor at a time: each parent closes once its child opens.
      defer { close(parent) }
      descriptor = try openLevel(name, in: parent)
    }
    return descriptor
  }

  /// The folder `name` inside the open folder `parent`, made private when missing, and
  /// opened without following a link, so a link where it belongs is refused.
  ///
  /// One that already exists is left as it is: whoever writes in it judges whose it is
  /// and its mode (`openPrivateFolder`).
  static func openLevel(_ name: String, in parent: Int32) throws(FileIOError) -> Int32 {
    let made = mkdirat(parent, name, mode_t(privateFolderMode)) == 0
    guard made || errno == EEXIST else { throw FileIOError(call: "mkdir", code: errno) }
    // On macOS a link opened with O_DIRECTORY and O_NOFOLLOW fails ENOTDIR, on Linux ELOOP.
    let flags = O_RDONLY | O_NOFOLLOW | O_DIRECTORY | O_CLOEXEC
    let descriptor = try check(openat(parent, name, flags), "open folder")
    if made {
      // mkdirat's mode is masked by the umask, which only ever clears bits, so the folder
      // is never more open than 0700; this restores any bit the umask cleared for this
      // user. A failure leaves it closed to every other user, so it is not an error.
      _ = fchmod(descriptor, mode_t(privateFolderMode))
    }
    return descriptor
  }

  /// The folder the walk starts from, and the names below it down to `folder`.
  ///
  /// The start is the deepest existing level above `owned`, so `owned` and every level
  /// below it are among the names, each then opened without following a link even when it
  /// already exists. `folder` must be a standardized absolute path inside `owned`, with no
  /// `..` among its components, since the walk climbs by dropping the last component; a
  /// path that is not, or an `owned` with no level above it, is refused as `EINVAL`.
  static func missingLevels(of folder: URL, owning owned: URL) throws(FileIOError)
    -> (URL, [String])
  {
    let parts = folder.pathComponents
    // How many components the path of the level just above `owned` has.
    let floor = owned.pathComponents.count - 1
    guard floor > 0, parts.starts(with: owned.pathComponents), !parts.contains("..") else {
      throw FileIOError(call: "folder path", code: EINVAL)
    }
    var base = folder.deletingLastPathComponent()
    var names = [folder.lastPathComponent]
    var info = stat()
    // lstat, so a link above `owned` counts as present and is then followed as found.
    while base.pathComponents.count > floor || lstat(base.path, &info) != 0 {
      names.insert(base.lastPathComponent, at: 0)
      base = base.deletingLastPathComponent()
    }
    return (base, names)
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
  static func writeAll(_ data: Data, to descriptor: Int32) throws {
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

import Foundation

/// How the app ends under its launch agent, whose plist restarts it only after a failed
/// exit or a crash (`KeepAlive` `SuccessfulExit` false).
public enum RunExit {
  /// A refusal no restart can cure, such as a data folder the app may not use: exit 0, so
  /// launchd leaves the agent stopped instead of restarting it every throttle interval.
  public static let refused: Int32 = EXIT_SUCCESS
  /// A failure a fresh copy may get past, such as a lock another copy holds: nonzero, so
  /// launchd starts a fresh copy after its throttle interval.
  public static let retry: Int32 = EXIT_FAILURE
}

/// The bound on the launch agent's two log files.
///
/// launchd opens each log for appending when it spawns the app and never rotates it, so a
/// copy that keeps failing would grow its error log forever. The app trims each log once,
/// at its start, which bounds a log to about `limit` plus what one run writes.
public enum LogCap {
  /// A log longer than this many bytes is trimmed at the app's start.
  public static let limit = 1 << 20
  /// How many of the log's last bytes a trim keeps, from the first whole line in them.
  public static let kept = 64 << 10
  /// The line break a kept tail starts after, so it never opens mid-line.
  private static let newline: UInt8 = 0x0A

  /// A positional read with `pread`'s shape: descriptor, buffer, byte count and offset in,
  /// the count of bytes read, or -1, out. A test passes one that fails or reads short.
  typealias PositionalRead = (Int32, UnsafeMutableRawPointer?, Int, off_t) -> Int

  /// Trim the log open at `descriptor` to its last whole lines when it is over `limit`.
  ///
  /// Only the launch agent's own log is trimmed: `descriptor` must be a regular file, and
  /// `path`, opened without following a link, must be that same file. Anything else, a
  /// terminal or a file a person redirected the app's output to, is left alone, as is a
  /// log whose tail cannot be read whole. Returns whether the log was trimmed.
  @discardableResult
  public static func trim(
    descriptor: Int32, path: URL, limit: Int = LogCap.limit, kept: Int = LogCap.kept
  ) -> Bool {
    trim(descriptor: descriptor, path: path, limit: limit, kept: kept, read: pread)
  }

  /// `trim`, its tail read through `read`, so a test can make that read fail or fall short.
  static func trim(
    descriptor: Int32, path: URL, limit: Int, kept: Int, read: PositionalRead
  ) -> Bool {
    let info = FileIO.status(of: descriptor)
    let size = Int(info.st_size)
    guard FileIO.isRegularFile(info), size > limit else { return false }
    guard let tail = tail(of: path, matching: info, count: min(kept, size), read: read) else {
      return false
    }
    guard ftruncate(descriptor, 0) == 0 else { return false }
    // A descriptor opened without O_APPEND would write its next byte at the old end,
    // leaving a hole the size of everything trimmed.
    lseek(descriptor, 0, SEEK_SET)
    // The log is already bounded here; a tail that cannot be written back is lost alone.
    _ = try? FileIO.writeAll(tail, to: descriptor)
    return true
  }

  /// The whole lines in the last `count` bytes of the file at `path`, or nil when `path`
  /// is not, without following a link, the file `info` describes, or when `read` fails or
  /// reads short: a trim must never replace the log with less than its tail.
  static func tail(of path: URL, matching info: stat, count: Int, read: PositionalRead) -> Data? {
    let reader = open(path.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
    guard reader >= 0 else { return nil }
    defer { close(reader) }
    let found = FileIO.status(of: reader)
    guard (found.st_dev, found.st_ino) == (info.st_dev, info.st_ino) else { return nil }
    // The byte before the window, when there is one, tells whether the window opens a line.
    let lead = Int(info.st_size) > count ? 1 : 0
    var buffer = [UInt8](repeating: 0, count: count + lead)
    let wanted = buffer.count
    let got = buffer.withUnsafeMutableBytes {
      read(reader, $0.baseAddress, wanted, off_t(Int(info.st_size) - wanted))
    }
    guard got == wanted else { return nil }
    return wholeLines(Data(buffer), lead: lead)
  }

  /// The window in `buffer`, which opens with `lead` bytes from before it, from its first
  /// whole line: just after the first line break in `buffer`, so a window that starts right
  /// after a break keeps its first line. A window that opens the file (`lead` 0) starts a
  /// line already, and one holding no break before its last byte is kept whole.
  static func wholeLines(_ buffer: Data, lead: Int) -> Data {
    guard lead > 0, let cut = buffer.firstIndex(of: newline), cut < buffer.endIndex - 1 else {
      return Data(buffer.dropFirst(lead))
    }
    return Data(buffer[(cut + 1)...])
  }
}

import Foundation

/// A one-connection HTTP listener the test itself owns, on the loopback address at a port
/// the kernel picks. It reaches no host service: it exists only so the real transport can
/// be proven at its socket boundary.
///
/// Every blocking call is bounded: `poll` waits 50 ms at a time, and each accepted socket
/// reads and writes with a 2 s timeout. `stop` closes every descriptor, and `deinit` calls
/// it, so a failing test cannot leave a listener behind.
final class LoopbackServer: @unchecked Sendable {
  /// What the listener does with the one connection it takes.
  enum Reply {
    /// Read the request, write these bytes, close.
    case bytes(Data)
    /// Read the request and never answer, holding the connection until `stop`.
    case silent
  }

  /// The port the kernel gave the listener.
  let port: Int
  private let listener: Int32
  private let lock = NSLock()
  private var stopped = false
  private var received = Data()
  private var held: Int32 = -1
  private let finished = DispatchSemaphore(value: 0)
  private let serving: Bool
  /// How long one poll of the listener waits, in milliseconds.
  private static let pollMilliseconds: Int32 = 50
  /// The read and write timeout on an accepted socket, in seconds.
  private static let socketTimeoutSeconds = 2
  /// The most of a request read.
  private static let maxRequestBytes = 1_048_576

  /// A listener answering one connection with `reply`; with nil it listens and never
  /// accepts, so a connection made to it stays pending, which `hasPendingConnection` sees.
  init(reply: Reply?) throws {
    listener = try Self.bindLoopback()
    port = try Self.boundPort(of: listener)
    serving = reply != nil
    if let reply {
      Thread { [self] in serve(reply) }.start()
    }
  }

  deinit {
    stop()
  }

  /// The request bytes the listener read.
  var request: Data {
    lock.withLock { received }
  }

  /// Whether a client has connected and is waiting to be accepted.
  func hasPendingConnection() -> Bool {
    var entry = pollfd(fd: listener, events: Int16(POLLIN), revents: 0)
    return poll(&entry, 1, 0) > 0
  }

  /// Stop serving and close every descriptor; safe to call more than once.
  func stop() {
    let first = lock.withLock {
      defer { stopped = true }
      return !stopped
    }
    guard first else { return }
    if serving { _ = finished.wait(timeout: .now() + .seconds(5)) }
    lock.withLock {
      if held >= 0 { close(held) }
      held = -1
    }
    close(listener)
  }

  private var isStopped: Bool {
    lock.withLock { stopped }
  }

  /// Accept one connection, read its request, and act on `reply`.
  private func serve(_ reply: Reply) {
    defer { finished.signal() }
    while !isStopped {
      var entry = pollfd(fd: listener, events: Int16(POLLIN), revents: 0)
      guard poll(&entry, 1, Self.pollMilliseconds) > 0 else { continue }
      let connection = accept(listener, nil, nil)
      guard connection >= 0 else { continue }
      Self.configure(connection)
      let bytes = Self.readRequest(connection)
      lock.withLock { received = bytes }
      switch reply {
      case .bytes(let answer):
        Self.writeAll(answer, to: connection)
        close(connection)
      case .silent:
        lock.withLock { held = connection }
      }
      return
    }
  }

  /// A stream socket bound to 127.0.0.1 at port 0 and listening.
  private static func bindLoopback() throws -> Int32 {
    let socketDescriptor = socket(AF_INET, SOCK_STREAM, 0)
    guard socketDescriptor >= 0 else { throw POSIXError(.EIO) }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = 0
    address.sin_addr.s_addr = in_addr_t(INADDR_LOOPBACK).bigEndian
    let bound = withUnsafePointer(to: &address) {
      $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
        bind(socketDescriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
      }
    }
    guard bound == 0, listen(socketDescriptor, 4) == 0 else {
      close(socketDescriptor)
      throw POSIXError(.EADDRNOTAVAIL)
    }
    return socketDescriptor
  }

  /// The port `descriptor` is bound to.
  private static func boundPort(of descriptor: Int32) throws -> Int {
    var address = sockaddr_in()
    var length = socklen_t(MemoryLayout<sockaddr_in>.size)
    let named = withUnsafeMutablePointer(to: &address) {
      $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
    }
    guard named == 0 else { throw POSIXError(.EIO) }
    return Int(UInt16(bigEndian: address.sin_port))
  }

  /// No SIGPIPE when the client has gone, and bounded reads and writes.
  private static func configure(_ connection: Int32) {
    var enabled: Int32 = 1
    setsockopt(connection, SOL_SOCKET, SO_NOSIGPIPE, &enabled, socklen_t(MemoryLayout<Int32>.size))
    var timeout = timeval(tv_sec: socketTimeoutSeconds, tv_usec: 0)
    let size = socklen_t(MemoryLayout<timeval>.size)
    setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &timeout, size)
    setsockopt(connection, SOL_SOCKET, SO_SNDTIMEO, &timeout, size)
  }

  /// The request's head and as much of its body as `Content-Length` names.
  private static func readRequest(_ connection: Int32) -> Data {
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while data.count < maxRequestBytes, !isComplete(data) {
      let count = read(connection, &buffer, buffer.count)
      if count <= 0 { break }
      data.append(buffer, count: count)
    }
    return data
  }

  /// Whether `data` holds a whole request: a head and the body its length names.
  private static func isComplete(_ data: Data) -> Bool {
    guard let end = data.range(of: Data("\r\n\r\n".utf8)) else { return false }
    let head = String(bytes: data[..<end.lowerBound], encoding: .utf8) ?? ""
    let length =
      head.split(separator: "\r\n").compactMap { line -> Int? in
        let parts = line.split(separator: ":", maxSplits: 1)
        guard parts.count == 2, parts[0].lowercased() == "content-length" else { return nil }
        return Int(parts[1].trimmingCharacters(in: .whitespaces))
      }.first ?? 0
    return data.count - end.upperBound >= length
  }

  /// Write `data`, stopping at the first failed write.
  private static func writeAll(_ data: Data, to connection: Int32) {
    data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
      var offset = 0
      while offset < raw.count {
        let start = raw.baseAddress.map { $0 + offset }
        let count = write(connection, start, raw.count - offset)
        if count <= 0 { return }
        offset += count
      }
    }
  }
}

/// An HTTP/1.1 answer with `status`, `headers` and `body`, closing the connection.
func httpAnswer(status: Int, headers: [String] = [], body: Data = Data()) -> Data {
  let lines = ["HTTP/1.1 \(status) Test", "Content-Length: \(body.count)", "Connection: close"]
  return Data((lines + headers).joined(separator: "\r\n").utf8) + Data("\r\n\r\n".utf8) + body
}

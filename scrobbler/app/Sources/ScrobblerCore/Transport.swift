import Foundation

/// What one POST came to: the store's answer, or a failure to get one.
public enum TransportResult: Sendable, Equatable {
  /// The store answered with `status` and up to the transport's cap of `body`.
  case response(status: Int, body: Data)
  /// No answer: refused, timed out, or not HTTP. The reason names no header or body.
  case failed(reason: String)
}

/// Posts one request. The drainer depends on this, so tests drive it with a fake and
/// never reach a network.
public protocol HTTPTransport: Sendable {
  /// POST `body` to `url` with `headers`.
  func post(_ url: URL, headers: [String: String], body: Data) async -> TransportResult
}

/// The real HTTP client for the loopback store.
///
/// It follows no redirect and uses no proxy, so the token in a request can only reach the
/// address it was sent to; each request times out after 10 s by default, and at most
/// 64 KiB of an answer is read. It keeps no cache, cookie or credential store.
///
/// Its tests drive it against a listener they bind on 127.0.0.1 themselves, so each of
/// these guarantees is proven at the socket, not only read back from the settings.
public final class LoopbackTransport: HTTPTransport {
  /// The per-request and whole-request timeout the app uses, in seconds.
  public static let defaultTimeout: TimeInterval = 10
  /// The most of an answer's body read.
  public static let maxBodyBytes = 64 * 1024

  /// This transport's per-request and whole-request timeout, in seconds.
  public let timeout: TimeInterval
  /// The session every request goes through.
  let session: URLSession

  /// A transport over a session built from `makeConfiguration`, refusing every redirect.
  /// The app takes the default; a test passes a short `timeout`.
  public init(timeout: TimeInterval = defaultTimeout) {
    self.timeout = timeout
    session = URLSession(
      configuration: Self.makeConfiguration(timeout: timeout), delegate: RedirectRefuser(),
      delegateQueue: nil)
  }

  /// POST `body` to `url` with `headers`, reading at most `maxBodyBytes` of the answer.
  public func post(_ url: URL, headers: [String: String], body: Data) async -> TransportResult {
    do {
      let request = Self.makeRequest(url, headers: headers, body: body, timeout: timeout)
      let (bytes, response) = try await session.bytes(for: request)
      let data = try await Self.collect(bytes, limit: Self.maxBodyBytes)
      return Self.result(for: response, body: data)
    } catch {
      return .failed(reason: Self.reason(for: error))
    }
  }

  /// An ephemeral session with every proxy off, the timeouts set, and no cache, cookie or
  /// credential store.
  static func makeConfiguration(timeout: TimeInterval = defaultTimeout)
    -> URLSessionConfiguration
  {
    let configuration = URLSessionConfiguration.ephemeral
    // A non-nil dictionary replaces the system's proxy settings; each kind is turned off.
    configuration.connectionProxyDictionary = [
      kCFNetworkProxiesHTTPEnable as String: false,
      kCFNetworkProxiesHTTPSEnable as String: false,
      kCFNetworkProxiesSOCKSEnable as String: false,
      kCFNetworkProxiesProxyAutoConfigEnable as String: false,
      kCFNetworkProxiesProxyAutoDiscoveryEnable as String: false,
    ]
    configuration.timeoutIntervalForRequest = timeout
    configuration.timeoutIntervalForResource = timeout
    configuration.waitsForConnectivity = false
    configuration.urlCache = nil
    configuration.httpCookieStorage = nil
    configuration.httpShouldSetCookies = false
    configuration.urlCredentialStorage = nil
    configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
    return configuration
  }

  /// A POST of `body` to `url` with `headers`, timing out after `timeout` seconds.
  static func makeRequest(
    _ url: URL, headers: [String: String], body: Data, timeout: TimeInterval = defaultTimeout
  ) -> URLRequest {
    var request = URLRequest(
      url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
    request.httpMethod = "POST"
    request.httpBody = body
    for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
    return request
  }

  /// At most `limit` bytes of `bytes`, which is not read past the cap.
  static func collect<Bytes: AsyncSequence>(_ bytes: Bytes, limit: Int) async throws -> Data
  where Bytes.Element == UInt8 {
    var data = Data()
    for try await byte in bytes {
      if data.count >= limit { break }
      data.append(byte)
    }
    return data
  }

  /// The result an answer `response` with `body` gives.
  static func result(for response: URLResponse, body: Data) -> TransportResult {
    guard let http = response as? HTTPURLResponse else {
      return .failed(reason: "not an HTTP response")
    }
    return .response(status: http.statusCode, body: body)
  }

  /// A failure's reason: only a URL error's code, never its description, which can quote
  /// the request.
  static func reason(for error: any Error) -> String {
    guard let urlError = error as? URLError else { return "transport error" }
    return "URL error \(urlError.code.rawValue)"
  }
}

/// Refuses every redirect, so a 3xx answer comes back as itself and the request with its
/// token is never sent on to another address.
final class RedirectRefuser: NSObject, URLSessionTaskDelegate, Sendable {
  /// Never follow: the redirect's response is the answer.
  func urlSession(
    _ session: URLSession, task: URLSessionTask,
    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest
  ) async -> URLRequest? {
    nil
  }
}

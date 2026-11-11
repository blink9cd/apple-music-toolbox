import Foundation
import Testing

@testable import ScrobblerCore

/// A URL no test ever sends to: requests are built, never resumed.
private let testURL = URL(fileURLWithPath: "/").deletingLastPathComponent()
  .appendingPathComponent("unused")
/// The store's address at its default port; built here, never contacted.
private let storeURL = ScrobblerConfig().submitURL

@Test func theSessionUsesNoProxyAndTheTimeout() {
  let configuration = LoopbackTransport.makeConfiguration()
  let proxies = configuration.connectionProxyDictionary ?? [:]
  for key in [
    kCFNetworkProxiesHTTPEnable, kCFNetworkProxiesHTTPSEnable, kCFNetworkProxiesSOCKSEnable,
    kCFNetworkProxiesProxyAutoConfigEnable, kCFNetworkProxiesProxyAutoDiscoveryEnable,
  ] {
    #expect(proxies[key as String] as? Bool == false, "\(key) should be off")
  }
  #expect(configuration.timeoutIntervalForRequest == 10)
  #expect(configuration.timeoutIntervalForResource == 10)
  #expect(configuration.urlCache == nil)
  #expect(configuration.httpCookieStorage == nil)
  #expect(configuration.urlCredentialStorage == nil)
  #expect(!configuration.waitsForConnectivity)
}

@Test func theTransportBuildsItsSessionFromThatConfiguration() {
  let transport = LoopbackTransport()
  #expect(transport.session.configuration.timeoutIntervalForResource == 10)
  #expect(transport.session.delegate is RedirectRefuser)
}

@Test func theRequestIsAPostWithTheHeadersAndBody() {
  let body = Data("{}".utf8)
  let request = LoopbackTransport.makeRequest(
    storeURL, headers: ["Content-Type": "application/json"], body: body)
  #expect(request.httpMethod == "POST")
  #expect(request.url == storeURL)
  #expect(request.httpBody == body)
  #expect(request.timeoutInterval == 10)
  #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
  #expect(request.cachePolicy == .reloadIgnoringLocalCacheData)
}

@Test func aRedirectIsNeverFollowed() async throws {
  let session = URLSession(configuration: .ephemeral)
  let task = session.dataTask(with: storeURL)
  let response = try #require(
    HTTPURLResponse(url: storeURL, statusCode: 302, httpVersion: nil, headerFields: nil))
  let next = await RedirectRefuser().urlSession(
    session, task: task, willPerformHTTPRedirection: response, newRequest: URLRequest(url: testURL))
  #expect(next == nil)
  session.invalidateAndCancel()
}

@Test func theBodyIsReadToTheCap() async throws {
  let bytes = AsyncStream<UInt8> { continuation in
    for byte in 0..<100 { continuation.yield(UInt8(byte)) }
    continuation.finish()
  }
  #expect(try await LoopbackTransport.collect(bytes, limit: 10) == Data((0..<10).map(UInt8.init)))
}

@Test func aShortBodyIsReadWhole() async throws {
  let bytes = AsyncStream<UInt8> { continuation in
    continuation.yield(1)
    continuation.finish()
  }
  #expect(try await LoopbackTransport.collect(bytes, limit: 10) == Data([1]))
  #expect(LoopbackTransport.maxBodyBytes == 65536)
}

@Test func anHTTPResponseGivesItsStatusAndBody() throws {
  let response = try #require(
    HTTPURLResponse(url: storeURL, statusCode: 503, httpVersion: nil, headerFields: nil))
  #expect(
    LoopbackTransport.result(for: response, body: Data([7]))
      == .response(status: 503, body: Data([7])))
}

@Test func aResponseThatIsNotHTTPFails() {
  let response = URLResponse(
    url: testURL, mimeType: nil, expectedContentLength: 0, textEncodingName: nil)
  #expect(
    LoopbackTransport.result(for: response, body: Data()) == .failed(reason: "not an HTTP response")
  )
}

@Test func aFailureReasonNamesOnlyTheErrorCode() {
  #expect(LoopbackTransport.reason(for: URLError(.timedOut)) == "URL error -1001")
  #expect(LoopbackTransport.reason(for: CocoaError(.fileNoSuchFile)) == "transport error")
}

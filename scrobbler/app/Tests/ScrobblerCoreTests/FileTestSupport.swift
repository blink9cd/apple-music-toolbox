import Foundation
import Testing

@testable import ScrobblerCore

/// A fresh folder under the system's temporary folder, removed with everything in it when
/// the last reference goes. Every file test works inside one, never under a real home.
final class TempFolder {
  /// The folder itself.
  let url: URL

  init() throws {
    url = FileManager.default.temporaryDirectory
      .appendingPathComponent("scrobbler-test-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
  }

  /// `name` inside the folder.
  func child(_ name: String) -> URL {
    url.appendingPathComponent(name)
  }

  deinit {
    try? FileManager.default.removeItem(at: url)
  }
}

/// An invented token: 64 lowercase hex characters no store ever issued.
let testToken = "5e0b7c1d9a2f4e6b8c3d1a0f7e9b2c4d6a8f0e1b3c5d7a9e2f4b6c8d0a1e3f5b"
/// An invented play ID in the contract's lowercase form.
let testPlayID = "0f8e2c4a-1b3d-4e5f-8a9b-0c1d2e3f4a5b"

/// A single listen carrying the queue file name's three parts, each settable.
func queuedListen(
  listenedAt: Int = 1_795_000_000, playID: String? = testPlayID, piece: Int? = 2
) throws -> ListenRecord {
  var record = try RecordCoding.decode(ListenRecord.self, from: minimalListen())
  record.payload[0].listenedAt = listenedAt
  record.payload[0].trackMetadata.additionalInfo.lsPlayID = playID
  record.payload[0].trackMetadata.additionalInfo.lsPiece = piece
  return record
}

/// Write `text` to `url` with the permission bits `mode`.
func writeFile(_ text: String, to url: URL, mode: Int = 0o600) throws {
  try Data(text.utf8).write(to: url)
  try setMode(mode, of: url)
}

/// Set `url`'s permission bits.
func setMode(_ mode: Int, of url: URL) throws {
  try FileManager.default.setAttributes([.posixPermissions: mode], ofItemAtPath: url.path)
}

/// The names directly inside `folder`, sorted.
func names(in folder: URL) throws -> [String] {
  try FileManager.default.contentsOfDirectory(atPath: folder.path).sorted()
}

import Foundation

/// Why a listen could not be named for the queue.
public enum QueueError: Error, Equatable, Sendable {
  /// The record is not a `single` submission of exactly one listen.
  case notASingleListen
  /// A part of the file name, named by its key, is absent from the record.
  case missingNamePart(String)
  /// A part of the file name, named by its key, is outside the name rule.
  case invalidNamePart(String)
}

/// Where an enqueued record was written.
public enum Enqueued: Equatable, Sendable {
  /// Into the queue, to be sent.
  case queued(URL)
  /// Into the refused folder, never to be sent: the record is larger than the queue reads.
  case refused(URL)

  /// The file the record was written to.
  public var file: URL {
    switch self {
    case .queued(let file), .refused(let file): file
    }
  }
}

/// The queue of listens waiting to be sent, and the folder of those the store refused.
///
/// One compact `single` record per file, named
/// `<listened_at, 10 digits>-<play id>-<piece, 3 digits>.json`, so name order is time
/// order and a folder import replays in the order the listens happened.
public struct QueueStore: Sendable {
  /// Records waiting to be sent.
  public let queueDir: URL
  /// Records the store refused, each beside a `.why.json` file of its findings.
  public let refusedDir: URL

  /// The suffix every record file carries.
  static let recordSuffix = ".json"
  /// The suffix of a refused record's findings file.
  static let findingsSuffix = ".why.json"
  /// The listen times a ten-digit name can hold.
  static let listenedAtRange = 0...9_999_999_999
  /// The pieces a three-digit name can hold, which is also the contract's range.
  static let pieceRange = 1...999
  /// The name's field widths.
  private static let listenedAtWidth = 10
  private static let pieceWidth = 3
  /// The largest listen the store takes, in bytes: `contract/defaults.json`'s
  /// `max_listen_size`, which a test pins.
  static let storeListenLimit = 10240
  /// Room for the record's envelope around its one listen (`listen_type`, `payload`), a
  /// few dozen bytes, with ample margin.
  static let envelopeMargin = 4096
  /// The largest queue file read. A bigger file holds a listen the store would refuse, so
  /// it is never sent; it is reported instead.
  public static let maxRecordBytes = storeListenLimit + envelopeMargin

  /// A queue in `queueDir`, refusing into `refusedDir`. Neither folder need exist yet.
  public init(queueDir: URL, refusedDir: URL) {
    self.queueDir = queueDir
    self.refusedDir = refusedDir
  }

  /// The findings beside a record too large for the queue to read back.
  static let oversizedFindings = Data(
    #"{"findings":["record larger than the store's per-listen limit"]}"#.utf8)

  /// Write `record` into the queue atomically. One whose encoding is larger than
  /// `maxRecordBytes` could never be read back to send, so it is written straight into the
  /// refused folder beside `oversizedFindings` instead.
  @discardableResult
  public func enqueue(_ record: ListenRecord) throws -> Enqueued {
    let name = try Self.fileName(for: record)
    let data = try RecordCoding.encode(record)
    guard data.count <= Self.maxRecordBytes else {
      try writeFindings(Self.oversizedFindings, beside: name)
      let file = refusedDir.appendingPathComponent(name)
      try FileIO.writeAtomically(data, to: file)
      return .refused(file)
    }
    let file = queueDir.appendingPathComponent(name)
    try FileIO.writeAtomically(data, to: file)
    return .queued(file)
  }

  /// Every record file directly inside the queue, in name order. An absent queue is empty.
  public func pending() throws -> [URL] {
    try Self.records(in: queueDir)
  }

  /// A queued record's bytes, read only when it is a regular file within `maxRecordBytes`.
  public func read(_ file: URL) throws(FileIOError) -> Data {
    try FileIO.readRegularFile(file, limit: Self.maxRecordBytes)
  }

  /// Delete a sent record. One already gone is fine; a folder is never removed.
  public func remove(_ file: URL) throws {
    try FileIO.unlinkIfPresent(file)
  }

  /// The `listened_at` a record file's name starts with, or nil when the name is not a
  /// record's: ten digits, a hyphen, and the rest of the name rule.
  public static func listenedAt(of file: URL) -> Int? {
    let name = file.lastPathComponent
    let digits = name.prefix(listenedAtWidth)
    guard isRecordName(name), digits.count == listenedAtWidth,
      digits.allSatisfy({ $0.isASCII && $0.isNumber }),
      name.dropFirst(listenedAtWidth).first == "-"
    else { return nil }
    return Int(digits)
  }

  /// Move a refused record to the refused folder, beside `findings` in `<name>.why.json`.
  ///
  /// The findings are written first: if the move then fails the record stays queued and is
  /// refused again on the next send, while the reverse order could leave a refused record
  /// with no reason beside it.
  public func refuse(_ file: URL, findings: Data) throws {
    try writeFindings(findings, beside: file.lastPathComponent)
    let target = refusedDir.appendingPathComponent(file.lastPathComponent)
    try FileIO.check(rename(file.path, target.path), "rename")
  }

  /// Write `findings` atomically into the refused folder, as the findings file of the
  /// record named `name`.
  private func writeFindings(_ findings: Data, beside name: String) throws {
    let stem = String(name.dropLast(Self.recordSuffix.count))
    try FileIO.writeAtomically(
      findings, to: refusedDir.appendingPathComponent(stem + Self.findingsSuffix))
  }

  /// How many records the store has refused.
  public func refusedCount() throws -> Int {
    try Self.records(in: refusedDir).count
  }

  /// The record files directly inside `folder`, in name order: no temp file, no findings,
  /// no folder. Any other entry with a record's name, a symlink or a FIFO, is listed, so
  /// its read refuses it and the drain reports it rather than hiding it.
  static func records(in folder: URL) throws -> [URL] {
    guard FileManager.default.fileExists(atPath: folder.path) else { return [] }
    return try FileManager.default.contentsOfDirectory(atPath: folder.path)
      .filter(isRecordName).sorted().map { folder.appendingPathComponent($0) }
      .filter { !FileIO.isFolderEntry($0) }
  }

  /// Whether `name` is a record's file name.
  static func isRecordName(_ name: String) -> Bool {
    name.hasSuffix(recordSuffix) && !name.hasSuffix(findingsSuffix) && !name.hasPrefix(".")
  }

  /// The queue file name for `record`, from its own `listened_at`, `ls_play_id` and
  /// `ls_piece`. The play ID must be the contract's lowercase UUID, so a name can never
  /// hold a path separator.
  static func fileName(for record: ListenRecord) throws(QueueError) -> String {
    guard record.listenType == .single, record.payload.count == 1, let listen = record.payload.first
    else { throw .notASingleListen }
    let info = listen.trackMetadata.additionalInfo
    guard let playID = info.lsPlayID else { throw .missingNamePart("ls_play_id") }
    guard let piece = info.lsPiece else { throw .missingNamePart("ls_piece") }
    guard listenedAtRange.contains(listen.listenedAt) else {
      throw .invalidNamePart("listened_at")
    }
    guard isPlayID(playID) else { throw .invalidNamePart("ls_play_id") }
    guard pieceRange.contains(piece) else { throw .invalidNamePart("ls_piece") }
    let time = zeroPadded(listen.listenedAt, to: listenedAtWidth)
    return "\(time)-\(playID)-\(zeroPadded(piece, to: pieceWidth))\(recordSuffix)"
  }

  /// Whether `text` is a lowercase UUID, the contract's play ID form.
  static func isPlayID(_ text: String) -> Bool {
    text.wholeMatch(of: /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/) != nil
  }

  /// `value`, which is not negative, in decimal with leading zeros to `width` digits.
  static func zeroPadded(_ value: Int, to width: Int) -> String {
    let digits = String(value)
    return String(repeating: "0", count: max(0, width - digits.count)) + digits
  }
}

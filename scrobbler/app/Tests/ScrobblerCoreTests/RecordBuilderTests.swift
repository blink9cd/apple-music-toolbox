import Foundation
import Testing

@testable import ScrobblerCore

/// An invented snapshot with every field set to a value inside the contract's bounds.
func fullSnapshot() -> TrackSnapshot {
  var snap = snapshot()
  snap.albumArtist = "Marsh Collective"
  snap.composer = "Invented Composer"
  snap.genre = "Harbor Pop"
  snap.year = 2019
  snap.trackNumber = 4
  snap.trackCount = 12
  snap.discNumber = 1
  snap.discCount = 2
  snap.compilation = false
  snap.bpm = 118
  snap.grouping = "Night Side"
  snap.work = "Harbor Suite"
  snap.movement = "Low Tide"
  snap.movementNumber = 2
  snap.movementCount = 4
  snap.rating = 80
  snap.favorited = true
  snap.disliked = false
  snap.albumFavorited = false
  snap.albumDisliked = true
  snap.kind = "AAC audio file"
  snap.bitRate = 256
  snap.sampleRate = 44_100
  snap.dateAdded = 1_700_000_000
  snap.playedCount = 9
  snap.skippedCount = 1
  snap.playedDate = 1_790_000_000
  return snap
}

/// A play of track one heard `heard` seconds, with `snap` read.
func builtPlay(_ snap: TrackSnapshot? = fullSnapshot(), heard: Double = 30.9) -> OpenPlay {
  OpenPlay(
    playID: playID(7), piece: 3, persistentID: trackOne, startedAt: base + 100.9,
    heardSeconds: heard, lastPositionMs: 30_000, durationMs: 215_000, snapshot: snap,
    noticeName: "Notice Title", noticeArtist: "Notice Artist", noticeAlbum: "Notice Album",
    pausedAt: nil)
}

/// The info of the listen built from `play`, which must build.
func builtInfo(_ play: OpenPlay) throws -> AdditionalInfo {
  info(try #require(RecordBuilder.listen(play)))
}

@Test func aListenCarriesThePlayAndEverySnapshotField() throws {
  let record = try #require(RecordBuilder.listen(builtPlay()))
  #expect(record.listenType == .single)
  #expect(record.payload[0].listenedAt == Int(base) + 100)
  let metadata = record.payload[0].trackMetadata
  #expect(metadata.artistName == "Velvet Marsh")
  #expect(metadata.trackName == "Paper Comet (Album Version)")
  #expect(metadata.releaseName == "Tin Harbor")
  let item = metadata.additionalInfo
  #expect(item.submissionClient == Layout.submissionClient)
  #expect(item.submissionClientVersion == Layout.version)
  #expect(item.mediaPlayer == "Music")
  #expect(item.mediaPlayerVersion == "9.9.1")
  #expect(item.durationMs == 215_000)
  #expect(item.durationPlayed == 30)
  #expect(item.lsPiece == 3)
  #expect(item.lsPlayID == playID(7))
  #expect(item.lsPersistentID == trackOne)
  #expect(item.lsSource == .localFile)
  #expect(item.lsFilePath == "/Volumes/Invented/Velvet Marsh/Paper Comet.m4a")
  #expect(item.lsMediaType == .music)
  #expect(item.tracknumber == "4")
  #expect(item.lsAlbumArtist == "Marsh Collective")
  #expect(item.lsGenre == "Harbor Pop")
  #expect(item.lsYear == 2019)
  #expect(item.lsDiscNumber == 1)
  #expect(item.lsComposer == "Invented Composer")
  #expect(item.lsTrackCount == 12)
  #expect(item.lsDiscCount == 2)
  #expect(item.lsCompilation == false)
  #expect(item.lsBpm == 118)
  #expect(item.lsGrouping == "Night Side")
  #expect(item.lsWork == "Harbor Suite")
  #expect(item.lsMovement == "Low Tide")
  #expect(item.lsMovementNumber == 2)
  #expect(item.lsMovementCount == 4)
  #expect(item.lsMusicRating == 80)
  #expect(item.lsMusicFavorited == true)
  #expect(item.lsMusicDisliked == false)
  #expect(item.lsMusicAlbumFavorited == false)
  #expect(item.lsMusicAlbumDisliked == true)
  #expect(item.lsKind == "AAC audio file")
  #expect(item.lsBitRate == 256)
  #expect(item.lsSampleRate == 44_100)
  #expect(item.lsMusicDateAdded == 1_700_000_000)
  #expect(item.lsMusicPlayedCount == 9)
  #expect(item.lsMusicSkippedCount == 1)
  #expect(item.lsMusicPlayedDate == 1_790_000_000)
  #expect(item.lsState == nil)
  #expect(item.lsPositionSeconds == nil)
}

@Test func musicZerosAndEmptyTextOmitTheirKeysButARatingOfZeroStays() throws {
  var snap = fullSnapshot()
  snap.bpm = 0
  snap.trackCount = 0
  snap.discCount = 0
  snap.movementNumber = 0
  snap.movementCount = 0
  snap.year = 0
  snap.trackNumber = 0
  snap.rating = 0
  snap.genre = ""
  snap.musicVersion = ""
  let item = try builtInfo(builtPlay(snap))
  #expect(item.lsBpm == nil)
  #expect(item.lsTrackCount == nil)
  #expect(item.lsDiscCount == nil)
  #expect(item.lsMovementNumber == nil)
  #expect(item.lsMovementCount == nil)
  #expect(item.lsYear == nil)
  #expect(item.tracknumber == nil)
  #expect(item.lsGenre == nil)
  #expect(item.mediaPlayerVersion == nil)
  #expect(item.lsMusicRating == 0)
}

@Test func anOptionalIntegerOutsideItsRangeIsOmitted() throws {
  var snap = fullSnapshot()
  snap.bpm = 1_000
  snap.trackCount = 10_000
  snap.bitRate = 100_001
  snap.sampleRate = 1_000_001
  snap.rating = 101
  snap.playedCount = 2_147_483_648
  snap.dateAdded = 253_402_300_800
  snap.year = 999
  var play = builtPlay(snap)
  play.durationMs = 2_073_600_001
  let item = try builtInfo(play)
  #expect(item.lsBpm == nil)
  #expect(item.lsTrackCount == nil)
  #expect(item.lsBitRate == nil)
  #expect(item.lsSampleRate == nil)
  #expect(item.lsMusicRating == nil)
  #expect(item.lsMusicPlayedCount == nil)
  #expect(item.lsMusicDateAdded == nil)
  #expect(item.lsYear == nil)
  #expect(item.durationMs == nil)
}

@Test func withoutALengthReadThePlayTakesTheSnapshotLength() throws {
  var play = builtPlay()
  play.durationMs = nil
  #expect(try builtInfo(play).durationMs == 214_500)
}

@Test func theSecondsHeardAreRoundedDownAndCappedAtTheContractMaximum() throws {
  #expect(try builtInfo(builtPlay(heard: 2.99)).durationPlayed == 2)
  #expect(try builtInfo(builtPlay(heard: 9e9)).durationPlayed == 2_073_600)
}

@Test func aPlayThatCannotBeRecordedWithinTheContractBuildsNothing() {
  var early = builtPlay()
  early.startedAt = 1_000
  #expect(RecordBuilder.listen(early) == nil)
  var late = builtPlay()
  late.startedAt = 1e300
  #expect(RecordBuilder.listen(late) == nil)
  #expect(RecordBuilder.listen(builtPlay(heard: -1)) == nil)
  #expect(RecordBuilder.listen(builtPlay(heard: .nan)) == nil)
  for piece in [0, 1_000] {
    var play = builtPlay()
    play.piece = piece
    #expect(RecordBuilder.listen(play) == nil)
  }
}

@Test func theNoticeFillsTheNamesTheSnapshotLacks() throws {
  let record = try #require(RecordBuilder.listen(builtPlay(nil)))
  let metadata = record.payload[0].trackMetadata
  #expect(metadata.artistName == "Notice Artist")
  #expect(metadata.trackName == "Notice Title")
  #expect(metadata.releaseName == "Notice Album")
  #expect(metadata.additionalInfo.mediaPlayerVersion == nil)
  #expect(metadata.additionalInfo.lsMediaType == nil)
  #expect(metadata.additionalInfo.lsSource == nil)
}

@Test func aTrackWithoutAnArtistOrTitleBuildsNothing() {
  var noArtist = builtPlay(nil)
  noArtist.noticeArtist = ""
  #expect(RecordBuilder.listen(noArtist) == nil)
  var noTitle = builtPlay(nil)
  noTitle.noticeName = nil
  #expect(RecordBuilder.listen(noTitle) == nil)
  var noAlbum = builtPlay(nil)
  noAlbum.noticeAlbum = nil
  #expect(RecordBuilder.listen(noAlbum)?.payload[0].trackMetadata.releaseName == nil)
}

@Test func anAlbumArtistMatchingTheArtistIsOmitted() throws {
  var snap = fullSnapshot()
  snap.albumArtist = "Velvet Marsh"
  #expect(try builtInfo(builtPlay(snap)).lsAlbumArtist == nil)
}

@Test func theSourceFollowsTheTrackClass() throws {
  var radio = fullSnapshot()
  radio.trackClass = "URL track"
  radio.location = nil
  #expect(try builtInfo(builtPlay(radio)).lsSource == .radio)
  var fileWithoutPath = fullSnapshot()
  fileWithoutPath.location = nil
  let missing = try builtInfo(builtPlay(fileWithoutPath))
  #expect(missing.lsSource == nil)
  #expect(missing.lsFilePath == nil)
  var shared = fullSnapshot()
  shared.trackClass = "shared track"
  let other = try builtInfo(builtPlay(shared))
  #expect(other.lsSource == nil)
  #expect(other.lsFilePath == nil)
}

@Test func theMediaTypeFollowsTheMediaKind() throws {
  let expected: [String: LsMediaType] = [
    "song": .music, "music video": .music, "podcast": .podcast, "audiobook": .audiobook,
    "movie": .other,
  ]
  for (kind, type) in expected {
    var snap = fullSnapshot()
    snap.mediaKind = kind
    #expect(try builtInfo(builtPlay(snap)).lsMediaType == type)
  }
}

@Test func aNowPlayingItemCarriesThePlayerStateAndNoListenKeys() throws {
  let record = try #require(
    RecordBuilder.nowPlaying(builtPlay(), state: .paused, positionMs: 97_250, at: base + 197.25))
  #expect(record.listenType == .playingNow)
  let item = record.payload[0].trackMetadata.additionalInfo
  #expect(item.lsState == .paused)
  #expect(item.lsPositionSeconds == 97.25)
  #expect(item.lsMeasuredAt == base + 197.25)
  #expect(item.lsRate == nil)
  #expect(item.lsPiece == nil)
  #expect(item.durationPlayed == nil)
  #expect(item.lsPlayID == playID(7))
  #expect(item.submissionClient == Layout.submissionClient)
}

@Test func aNowPlayingPositionIsHeldInsideTheContractRange() throws {
  let late = try #require(
    RecordBuilder.nowPlaying(builtPlay(), state: .playing, positionMs: Int.max, at: base))
  #expect(late.payload[0].trackMetadata.additionalInfo.lsPositionSeconds == 2_073_600)
  let early = try #require(
    RecordBuilder.nowPlaying(builtPlay(), state: .playing, positionMs: -5, at: base))
  #expect(early.payload[0].trackMetadata.additionalInfo.lsPositionSeconds == 0)
}

@Test func aNowPlayingItemOutsideTheContractBuildsNothing() {
  #expect(RecordBuilder.nowPlaying(builtPlay(), state: .playing, positionMs: 0, at: 1_000) == nil)
  #expect(RecordBuilder.nowPlaying(builtPlay(), state: .playing, positionMs: 0, at: .nan) == nil)
  var noArtist = builtPlay(nil)
  noArtist.noticeArtist = nil
  #expect(RecordBuilder.nowPlaying(noArtist, state: .playing, positionMs: 0, at: base) == nil)
}

@Test func everyBuiltRecordDecodesBackEqual() throws {
  let plays = [builtPlay(), builtPlay(nil), builtPlay(TrackSnapshot())]
  for play in plays {
    let listen = try #require(RecordBuilder.listen(play))
    let listenBytes = try RecordCoding.encode(listen)
    #expect(try RecordCoding.decode(ListenRecord.self, from: listenBytes) == listen)
    for state in [LsState.playing, .paused] {
      let now = try #require(
        RecordBuilder.nowPlaying(play, state: state, positionMs: 1_500, at: base + 1.5))
      let nowBytes = try RecordCoding.encode(now)
      #expect(try RecordCoding.decode(NowPlayingRecord.self, from: nowBytes) == now)
    }
  }
}

@Test func aSplitAtTheLastPieceClosesThePlayAndOpensANewOne() throws {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(pausedAt: base + 20, piece: 999), at: base + 5_000))
  let effects = engine.handle(.position(position(.playing, 50_000), at: base + 5_002))
  let record = try #require(enqueued(effects).first)
  #expect(info(record).lsPiece == 999)
  let play = try #require(engine.openPlay)
  #expect(play.playID == playID(1))
  #expect(play.piece == 1)
  #expect(play.snapshot == savedPlay().snapshot)
}

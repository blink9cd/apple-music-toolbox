import Foundation

extension AdditionalInfo {
  /// How one defined key is read, written and tested for presence.
  struct FieldCodec {
    /// The key the field codes.
    let key: CodingKeys
    /// Read the key, when present, into its property.
    let decode: (KeyedDecodingContainer<CodingKeys>, inout AdditionalInfo) throws -> Void
    /// Write the property under the key, when it is set.
    let encode: (AdditionalInfo, inout KeyedEncodingContainer<CodingKeys>) throws -> Void
    /// Whether the property is set.
    let isSet: (AdditionalInfo) -> Bool
  }

  /// The codec tying `key` to the property at `path`.
  static func field<Value: Codable>(
    _ key: CodingKeys, _ path: WritableKeyPath<AdditionalInfo, Value?>
  ) -> FieldCodec {
    FieldCodec(
      key: key,
      decode: { container, info in
        info[keyPath: path] = try container.decodeIfPresent(Value.self, forKey: key)
      },
      encode: { info, container in
        try container.encodeIfPresent(info[keyPath: path], forKey: key)
      },
      isSet: { $0[keyPath: path] != nil })
  }

  /// One codec per defined key, in `CodingKeys` order; a test holds it to that set exactly.
  static var fields: [FieldCodec] {
    [
      field(.artistMbids, \.artistMbids), field(.releaseGroupMbid, \.releaseGroupMbid),
      field(.releaseMbid, \.releaseMbid), field(.recordingMbid, \.recordingMbid),
      field(.trackMbid, \.trackMbid), field(.workMbids, \.workMbids),
      field(.tracknumber, \.tracknumber), field(.isrc, \.isrc), field(.spotifyID, \.spotifyID),
      field(.tags, \.tags), field(.mediaPlayer, \.mediaPlayer),
      field(.mediaPlayerVersion, \.mediaPlayerVersion),
      field(.submissionClient, \.submissionClient),
      field(.submissionClientVersion, \.submissionClientVersion),
      field(.originalSubmissionClient, \.originalSubmissionClient),
      field(.musicService, \.musicService), field(.musicServiceName, \.musicServiceName),
      field(.originURL, \.originURL), field(.label, \.label), field(.durationMs, \.durationMs),
      field(.duration, \.duration), field(.durationPlayed, \.durationPlayed),
      field(.durationPlayedMs, \.durationPlayedMs), field(.lsSource, \.lsSource),
      field(.lsMediaType, \.lsMediaType), field(.lsFilePath, \.lsFilePath),
      field(.lsPersistentID, \.lsPersistentID), field(.lsCatalogID, \.lsCatalogID),
      field(.lsPlayID, \.lsPlayID), field(.lsAlbumArtist, \.lsAlbumArtist),
      field(.lsDiscNumber, \.lsDiscNumber), field(.lsGenre, \.lsGenre), field(.lsYear, \.lsYear),
      field(.lsComposer, \.lsComposer), field(.lsTrackCount, \.lsTrackCount),
      field(.lsDiscCount, \.lsDiscCount), field(.lsCompilation, \.lsCompilation),
      field(.lsBpm, \.lsBpm), field(.lsGrouping, \.lsGrouping), field(.lsWork, \.lsWork),
      field(.lsMovement, \.lsMovement), field(.lsMovementNumber, \.lsMovementNumber),
      field(.lsMovementCount, \.lsMovementCount), field(.lsMusicRating, \.lsMusicRating),
      field(.lsMusicFavorited, \.lsMusicFavorited), field(.lsMusicDisliked, \.lsMusicDisliked),
      field(.lsMusicAlbumFavorited, \.lsMusicAlbumFavorited),
      field(.lsMusicAlbumDisliked, \.lsMusicAlbumDisliked), field(.lsKind, \.lsKind),
      field(.lsBitRate, \.lsBitRate), field(.lsSampleRate, \.lsSampleRate),
      field(.lsMusicDateAdded, \.lsMusicDateAdded),
      field(.lsMusicPlayedCount, \.lsMusicPlayedCount),
      field(.lsMusicSkippedCount, \.lsMusicSkippedCount),
      field(.lsMusicPlayedDate, \.lsMusicPlayedDate), field(.lsPiece, \.lsPiece),
      field(.lsPositionSeconds, \.lsPositionSeconds), field(.lsState, \.lsState),
      field(.lsRate, \.lsRate), field(.lsMeasuredAt, \.lsMeasuredAt),
    ]
  }
}

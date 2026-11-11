/// Music.app as the live layer finds it: by its bundle ID, and by the notice it posts.
public enum MusicApp {
  /// Music's bundle ID, which a running copy and a quitting one are both matched by.
  public static let bundleID = "com.apple.Music"
  /// The distributed notice Music posts on every change of player or track.
  public static let playerInfoNotice = "com.apple.Music.playerInfo"

  /// Whether an app with `bundleIdentifier` is Music; the match is exact.
  public static func isMusic(bundleIdentifier: String?) -> Bool {
    bundleIdentifier == bundleID
  }
}

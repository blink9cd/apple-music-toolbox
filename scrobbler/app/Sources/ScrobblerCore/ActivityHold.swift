/// The hold that keeps App Nap off while a track plays: one begun when playing starts,
/// ended when it stops, however often either is said.
///
/// The app passes `ProcessInfo`'s `beginActivity` and `endActivity`; tests pass recorders,
/// so the bookkeeping is proven without touching the real process.
@MainActor public final class ActivityHold<Token> {
  private let begin: () -> Token
  private let end: (Token) -> Void
  /// The activity begun and not yet ended; nil while nothing plays.
  private var token: Token?

  /// A hold that calls `begin` to start an activity and `end` to finish it.
  public init(begin: @escaping () -> Token, end: @escaping (Token) -> Void) {
    self.begin = begin
    self.end = end
  }

  /// Whether an activity is held now.
  public var isHeld: Bool { token != nil }

  /// Hold an activity while `playing`, and none otherwise.
  public func set(_ playing: Bool) {
    if playing {
      if token == nil { token = begin() }
    } else if let held = token {
      end(held)
      token = nil
    }
  }
}

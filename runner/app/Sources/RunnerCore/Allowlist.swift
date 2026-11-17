// The interpreter and scripts the runner may start, written at build into the
// bundle's Info.plist. It is trusted only after the runner has verified its own bundle's
// signature, which covers the Info.plist: see Supervisor.run.

/// The exact absolute interpreter path and script paths the runner may start.
public struct Allowlist: Equatable, Sendable {
  /// The Info.plist key the build writes the allowlist under.
  public static let infoKey = "AMTRunnerAllowlist"

  public let python: String
  public let scripts: [String]

  public init(python: String, scripts: [String]) {
    self.python = python
    self.scripts = scripts
  }

  /// Decode the Info.plist value, `["python": String, "scripts": [String]]`; nil when it is
  /// missing or any part has another shape.
  public init?(infoValue: Any?) {
    guard let value = infoValue as? [String: Any],
      let python = value["python"] as? String,
      let scripts = value["scripts"] as? [String]
    else { return nil }
    self.init(python: python, scripts: scripts)
  }

  /// Refuse `python` or `script` unless each matches an entry exactly. No path is
  /// normalized: the build writes the very strings its callers pass.
  public func check(python: String, script: String) throws(RunnerError) {
    guard python == self.python else { throw .notAllowed(python) }
    guard scripts.contains(script) else { throw .notAllowed(script) }
  }
}

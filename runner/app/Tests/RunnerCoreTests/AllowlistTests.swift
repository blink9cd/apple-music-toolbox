import Testing

@testable import RunnerCore

@Test func refusesAScriptNotAllowed() {
  let list = Allowlist(python: "/v/bin/python", scripts: ["/r/a.py"])
  #expect(throws: RunnerError.notAllowed("/r/b.py")) {
    try list.check(python: "/v/bin/python", script: "/r/b.py")
  }
}

@Test func refusesAnInterpreterNotAllowed() {
  let list = Allowlist(python: "/v/bin/python", scripts: ["/r/a.py"])
  #expect(throws: RunnerError.notAllowed("/usr/bin/python3")) {
    try list.check(python: "/usr/bin/python3", script: "/r/a.py")
  }
}

@Test func acceptsAnExactMatch() throws {
  let list = Allowlist(python: "/v/bin/python", scripts: ["/r/a.py", "/r/b.py"])
  try list.check(python: "/v/bin/python", script: "/r/b.py")
}

@Test func matchesTheExactStringOnly() {
  // No normalizing: a path that would resolve to an allowed one is still refused.
  let list = Allowlist(python: "/v/bin/python", scripts: ["/r/a.py"])
  #expect(throws: RunnerError.notAllowed("/r/./a.py")) {
    try list.check(python: "/v/bin/python", script: "/r/./a.py")
  }
}

@Test func decodesTheInfoPlistValue() {
  let value: [String: Any] = ["python": "/v/bin/python", "scripts": ["/r/a.py", "/r/b.py"]]
  #expect(
    Allowlist(infoValue: value)
      == Allowlist(python: "/v/bin/python", scripts: ["/r/a.py", "/r/b.py"]))
}

@Test func theInfoKeyIsTheBuildContract() {
  #expect(Allowlist.infoKey == "AMTRunnerAllowlist")
}

@Test func aMissingOrMalformedValueDecodesToNil() {
  #expect(Allowlist(infoValue: nil) == nil)
  #expect(Allowlist(infoValue: "not a dictionary") == nil)
  #expect(Allowlist(infoValue: ["scripts": ["/r/a.py"]] as [String: Any]) == nil)
  #expect(Allowlist(infoValue: ["python": 3, "scripts": ["/r/a.py"]] as [String: Any]) == nil)
  #expect(Allowlist(infoValue: ["python": "/v/p"] as [String: Any]) == nil)
  #expect(Allowlist(infoValue: ["python": "/v/p", "scripts": "/r/a.py"] as [String: Any]) == nil)
}

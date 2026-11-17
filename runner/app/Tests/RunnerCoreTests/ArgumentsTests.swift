import Testing

@testable import RunnerCore

@Test func parsesTheFullForm() throws {
  let call = try Arguments.parse([
    "--python", "/v/bin/python", "--script", "/r/tool.py", "--", "--mode", "run",
  ])
  #expect(
    call == Arguments(python: "/v/bin/python", script: "/r/tool.py", rest: ["--mode", "run"]))
}

@Test func takesTheTwoFlagsInEitherOrder() throws {
  let call = try Arguments.parse(["--script", "/r/tool.py", "--python", "/v/bin/python", "--"])
  #expect(call == Arguments(python: "/v/bin/python", script: "/r/tool.py", rest: []))
}

@Test func passesFlagLookalikesAfterTheSeparatorThrough() throws {
  let call = try Arguments.parse([
    "--python", "/v/p", "--script", "/r/a.py", "--", "--python", "--", "x",
  ])
  #expect(call.rest == ["--python", "--", "x"])
}

@Test func refusesARelativeScript() {
  #expect(throws: RunnerError.usage("--script must be an absolute path")) {
    try Arguments.parse(["--python", "/v/bin/python", "--script", "tool.py", "--"])
  }
}

@Test func refusesARelativeInterpreter() {
  #expect(throws: RunnerError.usage("--python must be an absolute path")) {
    try Arguments.parse(["--python", "python3", "--script", "/r/tool.py", "--"])
  }
}

@Test(arguments: [
  ([], "--python is required"),
  (["--script", "/r/a.py", "--"], "--python is required"),
  (["--python", "/v/p", "--"], "--script is required"),
  (["--python", "/v/p", "--script", "/r/a.py"], "-- must end the runner's own options"),
  (["--python", "/v/p", "--python", "/v/q", "--script", "/r/a.py", "--"], "--python given twice"),
  (
    ["--python", "/v/p", "--script", "/r/a.py", "--script", "/r/b.py", "--"],
    "--script given twice"
  ),
  (["--python", "/v/p", "--script", "/r/a.py", "--verbose", "--"], "unknown option: --verbose"),
  (["/r/a.py", "--"], "unknown option: /r/a.py"),
  (["--python"], "--python needs a value"),
  (["--python", "--", "x"], "--python needs a value"),
  (["--python", "/v/p", "--script"], "--script needs a value"),
])
func aBadCommandLineIsAUsageError(arguments: [String], message: String) {
  #expect(throws: RunnerError.usage(message)) {
    try Arguments.parse(arguments)
  }
}

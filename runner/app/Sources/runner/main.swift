// The runner's executable: it wires the live pieces into the tested Supervisor and exits
// with what it returns. Excluded from coverage as a real-host seam, so it holds no logic a
// test could reach.
import Foundation
import RunnerCore
import RunnerLive

exit(
  Supervisor.run(
    arguments: Array(CommandLine.arguments.dropFirst()),
    allowlist: {
      Allowlist(infoValue: Bundle.main.object(forInfoDictionaryKey: Allowlist.infoKey))
    },
    selfCheck: SelfCheck.bundleIsIntact,
    spawner: PosixSpawner(),
    report: { FileHandle.standardError.write(Data(($0 + "\n").utf8)) }))

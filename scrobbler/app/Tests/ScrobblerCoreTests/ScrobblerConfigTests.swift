import Foundation
import Testing

@testable import ScrobblerCore

/// Load a config file holding `text`.
private func load(_ text: String) throws -> ScrobblerConfig {
  let temp = try TempFolder()
  let url = temp.child("scrobbler.json")
  try writeFile(text, to: url)
  return try withExtendedLifetime(temp) { try ScrobblerConfig.load(from: url) }
}

@Test func theDefaultPortIsTheContractsStorePort() throws {
  #expect(try contractDefaults()["store_port"] as? Int == ScrobblerConfig.defaultStorePort)
}

@Test func theRelayPortIsTheContractsRelayPort() throws {
  #expect(try contractDefaults()["relay_port"] as? Int == ScrobblerConfig.defaultRelayPort)
}

@Test func anAbsentFileGivesTheDefaults() throws {
  let temp = try TempFolder()
  let config = try ScrobblerConfig.load(from: temp.child("scrobbler.json"))
  #expect(config == ScrobblerConfig())
  #expect(config.storePort == ScrobblerConfig.defaultStorePort)
  #expect(config.relayPort == ScrobblerConfig.defaultRelayPort)
}

@Test func anEmptyObjectGivesTheDefaults() throws {
  #expect(try load("{}") == ScrobblerConfig())
}

@Test func aValidPortIsRead() throws {
  #expect(try load(#"{"store_port": 50000}"#).storePort == 50000)
}

@Test func aValidRelayPortIsRead() throws {
  let config = try load(#"{"relay_port": 50001}"#)
  #expect(config.relayPort == 50001)
  #expect(config.storePort == ScrobblerConfig.defaultStorePort)
}

@Test func bothPortsAreReadTogether() throws {
  let config = try load(#"{"store_port": 50000, "relay_port": 50001}"#)
  #expect(config == ScrobblerConfig(storePort: 50000, relayPort: 50001))
}

@Test func theRelayURLIsTheLoopbackAtTheRelayPort() {
  let url = ScrobblerConfig(relayPort: 50001).relayURL
  #expect(url.absoluteString == "http://127.0.0.1:50001/1/submit-listens")
}

@Test func aRelayPortOutsideTheRangeGivesTheDefaultRelayURL() {
  #expect(ScrobblerConfig(relayPort: 70000).relayURL == ScrobblerConfig().relayURL)
}

@Test(arguments: [
  #"{"relay_port": "47832"}"#, #"{"relay_port": 80}"#, #"{"relay_port": 47831}"#,
  #"{"relay_port": 1023}"#, #"{"relay_port": 65536}"#, #"{"relay_port": 5000.5}"#,
  #"{"relay_port": null}"#, #"{"store_port": 50000, "relay_port": 50000}"#,
])
func aBadRelayPortIsRefusedNamingTheKey(text: String) {
  #expect(throws: ConfigError.invalidValue(key: "relay_port")) { try load(text) }
}

@Test func aStorePortAloneOnTheRelayPortIsRefusedNamingTheStorePort() {
  #expect(throws: ConfigError.invalidValue(key: "store_port")) {
    try load(#"{"store_port": 47832}"#)
  }
}

@Test func aStorePortOnTheDefaultRelayPortIsAcceptedOnceTheRelayMoves() throws {
  let config = try load(#"{"store_port": 47832, "relay_port": 50001}"#)
  #expect(config == ScrobblerConfig(storePort: 47832, relayPort: 50001))
}

@Test func theSubmitURLIsTheLoopbackAtThePort() {
  let url = ScrobblerConfig(storePort: 50000).submitURL
  #expect(url.absoluteString == "http://127.0.0.1:50000/1/submit-listens")
}

@Test func aPortOutsideTheRangeGivesTheDefaultURL() {
  #expect(ScrobblerConfig(storePort: -1).submitURL == ScrobblerConfig().submitURL)
}

@Test func anUnknownKeyIsRefusedByName() {
  #expect(throws: ConfigError.unknownKey("store_host")) {
    try load(#"{"store_port": 50000, "relay_port": 50001, "store_host": "x"}"#)
  }
}

@Test func anUnknownKeyThatIsNotANameIsNotEchoed() throws {
  let fileText = "color scheme from the file"
  let error = try #require(throws: ConfigError.self) { try load(#"{"\#(fileText)": 1}"#) }
  #expect(error == .unknownKey(ConfigError.unnamedKey))
  #expect(!error.key.contains(fileText))
}

@Test(arguments: [
  #"{"store_port": "47831"}"#, #"{"store_port": 80}"#, #"{"store_port": 47832}"#,
  #"{"store_port": 1023}"#, #"{"store_port": 65536}"#, #"{"store_port": 5000.5}"#,
  #"{"store_port": true}"#, #"{"store_port": null}"#,
])
func aBadPortIsRefusedNamingTheKey(text: String) {
  #expect(throws: ConfigError.invalidValue(key: "store_port")) { try load(text) }
}

@Test func theLowestAndHighestPortsAreAccepted() throws {
  #expect(try load(#"{"store_port": 1024}"#).storePort == 1024)
  #expect(try load(#"{"store_port": 65535}"#).storePort == 65535)
}

@Test(arguments: ["[]", "not json", #"{"store_port": "#, "\"text\""])
func aFileThatIsNotAnObjectIsRefused(text: String) {
  #expect(throws: ConfigError.notAnObject) { try load(text) }
}

@Test func aConfigFolderAtThePathIsUnreadable() throws {
  let temp = try TempFolder()
  let url = temp.child("scrobbler.json")
  try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
  #expect(throws: ConfigError.unreadable) { try ScrobblerConfig.load(from: url) }
}

@Test func aConfigThatCannotBeOpenedIsUnreadable() throws {
  let temp = try TempFolder()
  let url = temp.child("scrobbler.json")
  try writeFile("{}", to: url, mode: 0o000)
  #expect(throws: ConfigError.unreadable) { try ScrobblerConfig.load(from: url) }
}

@Test func aConfigOverTheCapIsUnreadable() throws {
  let padding = String(repeating: " ", count: ScrobblerConfig.maxFileBytes)
  #expect(throws: ConfigError.unreadable) { try load("{" + padding + "}") }
}

@Test func everyErrorNamesItsKey() {
  #expect(ConfigError.unreadable.key == ConfigError.wholeFile)
  #expect(ConfigError.notAnObject.key == ConfigError.wholeFile)
  #expect(ConfigError.unknownKey("a").key == "a")
  #expect(ConfigError.invalidValue(key: "store_port").key == "store_port")
}

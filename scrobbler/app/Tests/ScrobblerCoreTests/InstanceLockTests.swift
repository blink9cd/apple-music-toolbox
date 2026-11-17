import Foundation
import Testing

@testable import ScrobblerCore

/// The lock an attempt took, or nil when it took none.
func taken(_ attempt: LockAttempt) -> InstanceLock? {
  guard case .acquired(let lock) = attempt else { return nil }
  return lock
}

@Test func aSecondAcquireIsHeldWhileTheFirstIsHeld() throws {
  let temp = try TempFolder()
  let url = temp.child("state/scrobbler.lock")
  var first = taken(InstanceLock.acquire(at: url, owning: temp.url))
  #expect(first != nil)
  #expect(InstanceLock.acquire(at: url, owning: temp.url).isHeld)
  first = nil
  #expect(taken(InstanceLock.acquire(at: url, owning: temp.url)) != nil)
  _ = first
}

@Test func aLockWhoseFolderIsAFileIsUnopenable() throws {
  let temp = try TempFolder()
  try writeFile("x", to: temp.child("state"))
  let attempt = InstanceLock.acquire(at: temp.child("state/scrobbler.lock"), owning: temp.url)
  #expect(attempt.isUnopenable)
  #expect(!attempt.isHeld)
}

@Test func aSymlinkAtTheLockPathIsUnopenable() throws {
  let temp = try TempFolder()
  try writeFile("x", to: temp.child("target"))
  try FileManager.default.createDirectory(
    at: temp.child("state"), withIntermediateDirectories: true)
  let url = temp.child("state/scrobbler.lock")
  try FileManager.default.createSymbolicLink(at: url, withDestinationURL: temp.child("target"))
  #expect(InstanceLock.acquire(at: url, owning: temp.url).isUnopenable)
}

@Test func anAcquiredLockIsNeitherHeldNorUnopenable() throws {
  let temp = try TempFolder()
  let attempt = InstanceLock.acquire(at: temp.child("scrobbler.lock"), owning: temp.url)
  #expect(!attempt.isHeld)
  #expect(!attempt.isUnopenable)
  #expect(taken(attempt) != nil)
}

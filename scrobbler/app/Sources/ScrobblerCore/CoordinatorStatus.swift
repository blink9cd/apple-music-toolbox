import Foundation

// The coordinator's `status.json`: what it writes, and from where each field comes.
extension Coordinator {
  /// The snapshot of this moment: the coordinator's own counts, the drainer's sending
  /// state and the queue's two folders.
  func statusSnapshot() -> StatusSnapshot {
    var status = StatusSnapshot(pid: Int(pid), startedAt: startedAt, heartbeatAt: clock())
    status.musicRunning = bridge.isMusicRunning()
    status.playing = playing
    status.lastQueuedAt = lastQueuedAt
    status.lastSentAt = drainer.lastSentAt
    status.unrecordableCount = unrecordableCount
    status.automationDenied = automationDenied
    status.automationAskedAt = automationAskedAt
    status.nowPlaying = nowPlaying
    var queueError: String?
    do {
      let pending = try queue.pending()
      status.queueBacklog = pending.count
      status.oldestQueuedAt = pending.compactMap(QueueStore.listenedAt(of:)).min().map(Double.init)
      status.refusedCount = try queue.refusedCount()
    } catch {
      queueError = "queue unreadable"
    }
    // A listen that could not be queued is lost, so it outranks a send that will be retried;
    // a folder that cannot be listed comes next, since the drainer may not have seen it yet.
    status.lastSendError = queueWriteError ?? queueError ?? drainer.lastError
    return status
  }

  /// Replace `status.json` with this moment's snapshot, and note whether a request's
  /// pending time went with it. A write can fail after its rename, with the new file
  /// already in place, so a pending time counts as on disk from the attempt on, and as
  /// gone only once a write without one succeeds.
  func writeStatus() {
    pendingTimeOnDisk = pendingTimeOnDisk || automationAskedAt != nil
    do {
      try state.writeStatus(statusSnapshot())
      pendingTimeOnDisk = automationAskedAt != nil
    } catch {
      log.error("status not written: \(String(describing: error))")
    }
  }
}

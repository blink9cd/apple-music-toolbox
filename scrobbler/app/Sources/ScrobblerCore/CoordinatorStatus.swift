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

  /// Replace `status.json` with this moment's snapshot.
  func writeStatus() {
    do {
      try state.writeStatus(statusSnapshot())
    } catch {
      log.error("status not written: \(String(describing: error))")
    }
  }
}

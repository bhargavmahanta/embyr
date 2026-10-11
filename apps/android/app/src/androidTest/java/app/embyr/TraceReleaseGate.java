package app.embyr;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** One-shot, bounded release of an instrumentation-only trace holder. */
final class TraceReleaseGate {
    private final String nonce;
    private final long timeoutMs;
    private final CountDownLatch acknowledged = new CountDownLatch(1);
    private boolean ready, accepted, closed;
    private long readyNs, ackNs;

    TraceReleaseGate(String nonce, long timeoutMs) {
        if (nonce == null || !nonce.matches("[0-9a-f]{32}") || timeoutMs < 1 || timeoutMs > 15_000) {
            throw new IllegalArgumentException("Invalid bounded trace holder");
        }
        this.nonce = nonce;
        this.timeoutMs = timeoutMs;
    }

    synchronized void ready(long nowNs) {
        if (ready || closed) throw new IllegalStateException("Trace holder already started");
        readyNs = nowNs;
        ready = true;
    }

    synchronized boolean accept(String observedNonce, long nowNs) {
        long elapsed = nowNs - readyNs;
        if (!ready || closed || accepted || !nonce.equals(observedNonce) ||
                elapsed < 0 || elapsed >= TimeUnit.MILLISECONDS.toNanos(timeoutMs)) return false;
        accepted = true;
        ackNs = nowNs;
        acknowledged.countDown();
        return true;
    }

    synchronized long ackNs() { return ackNs; }

    boolean await() throws InterruptedException {
        synchronized (this) {
            if (!ready || closed) throw new IllegalStateException("Trace holder is not ready");
        }
        try {
            return acknowledged.await(timeoutMs, TimeUnit.MILLISECONDS);
        } finally {
            synchronized (this) { closed = true; }
        }
    }
}

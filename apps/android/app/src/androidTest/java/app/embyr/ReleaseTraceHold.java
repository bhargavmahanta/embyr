package app.embyr;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Bundle;
import android.os.SystemClock;
import org.json.JSONObject;

/** Keeps the instrumented target alive while its owned recorder drains. No app data access. */
final class ReleaseTraceHold implements AutoCloseable {
    static final String ACTION = "app.embyr.alpha.test.M706_TRACE_RELEASE";
    private final Context context;
    private final TraceReleaseGate gate;
    private final String nonce;
    private final BroadcastReceiver receiver;
    private boolean registered;
    private long readyNs, releasedNs;
    private boolean acknowledged;

    ReleaseTraceHold(Context context, String nonce) {
        if (!"app.embyr.alpha".equals(context.getPackageName())) {
            throw new IllegalArgumentException("Wrong trace-holder package");
        }
        this.context = context;
        this.nonce = nonce;
        gate = new TraceReleaseGate(nonce, 15_000);
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context ignored, Intent intent) {
                if (ACTION.equals(intent.getAction()) &&
                        "app.embyr.alpha".equals(intent.getPackage())) {
                    long now = SystemClock.elapsedRealtimeNanos();
                    gate.accept(intent.getStringExtra("nonce"), now);
                }
            }
        };
        // Shell holds DUMP. Ordinary applications cannot release the ephemeral receiver.
        context.registerReceiver(receiver, new IntentFilter(ACTION), "android.permission.DUMP",
            null, Context.RECEIVER_EXPORTED);
        registered = true;
    }

    Bundle readyStatus() {
        readyNs = SystemClock.elapsedRealtimeNanos();
        gate.ready(readyNs);
        Bundle status = new Bundle();
        status.putString("class", "app.embyr.AlphaPlatformRunner");
        status.putString("test", "releaseForestPerformanceCollection");
        status.putInt("numtests", 1);
        status.putInt("current", 1);
        status.putString("m706_trace_ready", nonce);
        return status;
    }

    boolean awaitRelease() throws InterruptedException {
        try {
            acknowledged = gate.await();
            return acknowledged;
        } finally { releasedNs = SystemClock.elapsedRealtimeNanos(); }
    }

    JSONObject receipt() throws org.json.JSONException {
        return new JSONObject().put("max_hold_ms", 15_000).put("ready_elapsed_ns", readyNs)
            .put("ack_elapsed_ns", gate.ackNs()).put("released_elapsed_ns", releasedNs)
            .put("acknowledged", acknowledged).put("receiver_unregistered", !registered);
    }

    @Override public void close() {
        if (registered) {
            context.unregisterReceiver(receiver);
            registered = false;
        }
    }
}

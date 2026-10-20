package app.embyr;

import android.graphics.Rect;
import android.os.SystemClock;
import android.os.Handler;
import android.os.Looper;
import android.view.Choreographer;
import android.view.InputDevice;
import android.view.MotionEvent;
import androidx.compose.ui.platform.ComposeView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Main-thread synthetic pointer workload; bypasses system injection, never changes camera directly. */
final class ForestFrameMotion implements Choreographer.FrameCallback {
    private final ComposeView view;
    private final Rect bounds;
    private final MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[2];
    private final MotionEvent.PointerCoords[] coordinates = new MotionEvent.PointerCoords[2];
    private final int[] origin = new int[2];
    private final long[] intended = new long[4096], actual = new long[4096];
    private final int[] routed = new int[4096];
    private Choreographer choreographer;
    private long epoch, downTime;
    private volatile boolean active, scheduled, stopped, stopRequested;
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean cancelAttempted, cancelCompleted, cancelRouted;
    private volatile Throwable cleanupFailure;
    private volatile Throwable failure;
    private volatile int count;
    ForestFrameMotion(ComposeView view, Rect bounds) {
        this.view = view; this.bounds = new Rect(bounds);
        for (int i = 0; i < 2; i++) {
            properties[i] = new MotionEvent.PointerProperties(); properties[i].id = i;
            properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coordinates[i] = new MotionEvent.PointerCoords(); coordinates[i].pressure = 1; coordinates[i].size = 1;
        }
    }
    private void position(long elapsed) {
        float x = bounds.exactCenterX() + ForestMotionPath.x(elapsed);
        float y = bounds.exactCenterY() + ForestMotionPath.y(elapsed);
        float radius = ForestMotionPath.radius(elapsed);
        for (int i = 0; i < 2; i++) {
            coordinates[i].x = x + (i == 0 ? -radius : radius); coordinates[i].y = y;
            if (!bounds.contains((int) coordinates[i].x, (int) coordinates[i].y))
                throw new AssertionError("Motion leaves canvas");
        }
    }
    private void event(int action, int pointers) {
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, pointers,
            properties, coordinates, 0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            view.getLocationOnScreen(origin);
            event.offsetLocation(-origin[0], -origin[1]);
            for (int i = 0; i < pointers; i++) {
                if (Math.abs(event.getRawX(i) - coordinates[i].x) > .02f ||
                    Math.abs(event.getRawY(i) - coordinates[i].y) > .02f ||
                    Math.abs(event.getX(i) + origin[0] - coordinates[i].x) > .02f ||
                    Math.abs(event.getY(i) + origin[1] - coordinates[i].y) > .02f)
                    throw new AssertionError("Raw/local pointer coordinate mismatch");
            }
            boolean dispatched = view.dispatchTouchEvent(event);
            if (action == MotionEvent.ACTION_CANCEL) cancelRouted = dispatched;
            else if (!dispatched) throw new AssertionError("Pointer event not routed");
        } finally { event.recycle(); }
    }
    private void bounded(Runnable operation, boolean cleanup) {
        CountDownLatch done = new CountDownLatch(1);
        if (!main.post(() -> {
            try { operation.run(); }
            catch (Throwable error) { failure = error; if (cleanup) cleanupFailure = error; }
            finally { done.countDown(); }
        })) { failure = new AssertionError("Main callback rejected"); if (cleanup) cleanupFailure = failure; }
        else {
            try {
                if (!done.await(2, TimeUnit.SECONDS)) {
                    stopRequested = true; failure = new AssertionError("Main callback timeout");
                    if (cleanup) cleanupFailure = failure;
                }
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt(); stopRequested = true; failure = error;
                if (cleanup) cleanupFailure = error;
            }
        }
        check();
    }
    void startBounded() {
        bounded(() -> { if (!stopRequested) startOwned(); }, false);
    }
    private void startOwned() {
        if (choreographer != null) throw new AssertionError("Motion already started");
        choreographer = Choreographer.getInstance(); epoch = System.nanoTime(); downTime = SystemClock.uptimeMillis();
        position(0); active = true; event(MotionEvent.ACTION_DOWN, 1);
        if (stopRequested) { stopOwned(); return; }
        event(MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2);
        if (stopRequested) { stopOwned(); return; }
        scheduled = true; choreographer.postFrameCallback(this);
    }
    @Override public void doFrame(long frameTimeNanos) {
        scheduled = false;
        if (stopped || stopRequested) return;
        try {
            if (count >= actual.length) throw new AssertionError("Motion telemetry overflow");
            long now = System.nanoTime(); intended[count] = frameTimeNanos; actual[count] = now;
            int index = count++;
            position(now - epoch); event(MotionEvent.ACTION_MOVE, 2); routed[index] = 1;
            // Exactly one next callback; no accumulated inputs or catch-up frames.
            if (!stopRequested) { scheduled = true; choreographer.postFrameCallback(this); }
        } catch (Throwable error) { failure = error; stopped = true; }
    }
    void check() { if (failure != null) throw new AssertionError("Motion workload failed", failure); }
    long epoch() { return epoch; }
    int moves() { return count; }
    void stopBounded() {
        stopRequested = true;
        bounded(this::stopOwned, true);
    }
    private void stopOwned() {
        stopped = true;
        if (scheduled) { choreographer.removeFrameCallback(this); scheduled = false; }
        if (active) {
            cancelAttempted = true;
            try { event(MotionEvent.ACTION_CANCEL, 2); cancelCompleted = true; }
            catch (Throwable error) { cleanupFailure = error; if (failure == null) failure = error; }
            finally { active = false; }
        }
    }
    JSONObject evidence() throws Exception {
        JSONArray ticks = new JSONArray(); long missed = 0;
        for (int i = 0; i < count; i++) {
            if (i > 0) missed += Math.max(0, Math.round((intended[i] - intended[i-1]) / (1e9 / 60)) - 1);
            ticks.put(new JSONObject().put("intended_ns", intended[i]).put("actual_ns", actual[i]).put("routed", routed[i] == 1));
        }
        return new JSONObject().put("epoch_ns", epoch).put("ticks", ticks).put("missed_input_ticks", missed)
            .put("cleanup_complete", stopped && !scheduled && !active && cancelCompleted && cleanupFailure == null)
            .put("callback_scheduled", scheduled).put("cancel_attempted", cancelAttempted)
            .put("cancel_completed", cancelCompleted).put("cancel_routed", cancelRouted)
            .put("cleanup_error_type", cleanupFailure == null ? JSONObject.NULL : cleanupFailure.getClass().getSimpleName())
            .put("scope", "Synthetic production-pointer workload; no system-input or latency equivalence claim")
            .put("routing_is_not_movement_consumption", true).put("failure_type", failure == null ? JSONObject.NULL : failure.getClass().getSimpleName());
    }
}

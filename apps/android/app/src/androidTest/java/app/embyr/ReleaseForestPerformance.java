package app.embyr;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.Rect;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.Trace;
import android.provider.Settings;
import android.view.FrameMetrics;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.Window;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.compose.runtime.Composer;
import androidx.compose.ui.platform.ComposeView;
import app.embyr.core.model.WorldNodeDto;
import app.embyr.feature.world.ForestCanvasKt;
import java.io.File;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import kotlin.Unit;
import kotlin.jvm.functions.Function2;
import org.json.JSONArray;
import org.json.JSONObject;

/** Test APK only. Framework samples and real input; no persistence, API, grading or app flags. */
public final class ReleaseForestPerformance {
    private ReleaseForestPerformance() {}
    private static String partialEvidence;
    public static String partialJson() { return partialEvidence; }
    private static final long SECOND = 1_000_000_000L;
    private static final String FOREST = "Forest map. Select a tree using the list below, or pan and pinch to zoom.";

    private static String sha(String value) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)))
            result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }

    private static JSONArray synthetic(int count) throws Exception {
        JSONArray result = new JSONArray();
        for (int i = 0; i < count; i++) {
            result.put(new JSONObject()
                .put("id", String.format(Locale.ROOT, "%08x-0000-4000-8000-000000000001", i + 1))
                .put("entity_id", String.format(Locale.ROOT, "%08x-0000-4000-8000-000000000002", i + 1))
                .put("entity_version", 1).put("region_id", "00000000-0000-4000-8000-000000000003")
                .put("logical_x", (i % 25 + 0.5) / 25.0).put("logical_y", (i / 25 + 0.5) / Math.ceil(count / 25.0))
                .put("depth", 0).put("visual_archetype", "branching_tree")
                .put("visual_seed", sha("m705-synthetic-" + i))
                .put("growth_state", new String[] { "SEED", "SPROUT", "YOUNG" }[i % 3]).put("revision", i + 1));
        }
        return result;
    }

    private static JSONArray real(Context context, String owner) throws Exception {
        File file = context.getDatabasePath("embyr-private.db");
        if (!file.isFile()) throw new AssertionError("Existing owner cache required");
        JSONArray nodes = new JSONArray();
        // One bounded SELECT: no transaction-control interception, writes or window refills.
        try (SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getPath(), null,
                SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS)) {
            if (!db.isReadOnly() || db.getVersion() != 4) throw new AssertionError("Readonly Room4 required");
            try (Cursor cursor = db.rawQuery("SELECT objectId,payloadJson FROM world_nodes WHERE ownerId=? ORDER BY objectId LIMIT 501", new String[] { owner })) {
                android.database.sqlite.SQLiteCursor nativeCursor = (android.database.sqlite.SQLiteCursor) cursor;
                int count = cursor.getCount();
                if (count < 1 || count > 500 || !cursor.moveToFirst() || nativeCursor.getWindow().getStartPosition() != 0 || nativeCursor.getWindow().getNumRows() != count)
                    throw new AssertionError("Complete nonempty real scene required");
                do {
                    JSONObject node = new JSONObject(cursor.getString(1));
                    if (!cursor.getString(0).equals(node.getString("id"))) throw new AssertionError("Cache object identity mismatch");
                    nodes.put(node);
                } while (cursor.moveToNext());
            }
        }
        return nodes;
    }

    private static List<WorldNodeDto> decode(JSONArray scene) throws Exception {
        ArrayList<WorldNodeDto> nodes = new ArrayList<>();
        for (int i = 0; i < scene.length(); i++) {
            JSONObject n = scene.getJSONObject(i);
            double x = n.getDouble("logical_x"), y = n.getDouble("logical_y");
            String growth = n.getString("growth_state"), seed = n.getString("visual_seed");
            String uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
            if (!n.getString("id").matches(uuid) || !n.getString("entity_id").matches(uuid) || !n.getString("region_id").matches(uuid) ||
                n.getInt("depth") != 0 || !Double.isFinite(x) || !Double.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1 ||
                !seed.matches("[0-9a-f]{64}") || !java.util.Arrays.asList("SEED", "SPROUT", "YOUNG").contains(growth) ||
                !"branching_tree".equals(n.getString("visual_archetype")) || n.getLong("entity_version") < 1 || n.getLong("revision") < 1 || n.getLong("revision") > 2147483647L)
                throw new AssertionError("Invalid frozen scene");
            nodes.add(new WorldNodeDto(n.getString("id"), n.getString("entity_id"), n.getLong("entity_version"),
                n.getString("region_id"), x, y, n.getInt("depth"), n.getString("visual_archetype"), seed, growth, n.getLong("revision")));
        }
        return nodes;
    }

    public static JSONObject sceneIdentity(Context context, String sceneName, String owner) throws Exception {
        if (!java.util.Arrays.asList("real", "100", "500").contains(sceneName)) throw new AssertionError("Unsupported scene");
        JSONArray scene = "real".equals(sceneName) ? real(context, owner) : synthetic(Integer.parseInt(sceneName));
        decode(scene);
        return new JSONObject().put("scene", sceneName).put("node_count", scene.length()).put("scene_sha256", sha(scene.toString()));
    }

    private static void content(ComposeView view, List<WorldNodeDto> nodes) {
        Function2<Composer, Integer, Unit> header = (composer, flags) -> Unit.INSTANCE;
        view.setContent((Function2<Composer, Integer, Unit>) (composer, flags) -> {
            ForestCanvasKt.NativeForest(nodes, Collections.emptyMap(), null, true, header, composer, 0, 4);
            return Unit.INSTANCE;
        });
    }

    private static ComposeView present(MainActivity activity, List<WorldNodeDto> nodes) throws Exception {
        Constructor<?> match = null;
        for (Constructor<?> candidate : ComposeView.class.getDeclaredConstructors()) {
            Class<?>[] parameters = candidate.getParameterTypes();
            if (parameters.length == 1 && parameters[0].isInstance(activity)) {
                if (match != null) throw new AssertionError("Ambiguous ComposeView constructor");
                match = candidate;
            }
        }
        if (match == null) throw new AssertionError("No compatible ComposeView constructor");
        match.setAccessible(true);
        ComposeView view = (ComposeView) match.newInstance(activity);
        // Same 24dp horizontal inset and 320dp production canvas for all scenes.
        int padding = Math.round(24 * activity.getResources().getDisplayMetrics().density);
        view.setPadding(padding, padding, padding, padding);
        content(view, nodes);
        activity.setContentView(view);
        return view;
    }

    private static AccessibilityNodeInfo find(AccessibilityNodeInfo node, String text, boolean prefix) {
        if (node == null) return null;
        String label = String.valueOf(node.getText());
        String description = String.valueOf(node.getContentDescription());
        if ((prefix ? label.startsWith(text) : label.equals(text)) || description.equals(text)) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo result = find(node.getChild(i), text, prefix);
            if (result != null) return result;
        }
        return null;
    }

    private static void click(Instrumentation instrument, String label, boolean prefix) {
        AccessibilityNodeInfo node = find(instrument.getUiAutomation().getRootInActiveWindow(), label, prefix);
        while (node != null && !node.isClickable()) node = node.getParent();
        if (node == null || !node.isVisibleToUser() || !node.isEnabled() || !node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            throw new AssertionError("Required production action unavailable");
    }

    private static final class Gesture {
        final Instrumentation instrument;
        final Rect bounds;
        final MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[2];
        final MotionEvent.PointerCoords[] coordinates = new MotionEvent.PointerCoords[2];
        long downTime;
        boolean active;
        long moves;
        Gesture(Instrumentation instrument, Rect bounds) {
            this.instrument = instrument; this.bounds = bounds;
            for (int i = 0; i < 2; i++) {
                properties[i] = new MotionEvent.PointerProperties(); properties[i].id = i; properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
                coordinates[i] = new MotionEvent.PointerCoords(); coordinates[i].pressure = 1; coordinates[i].size = 1;
            }
        }
        void event(int action, int count) {
            MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, count, properties, coordinates, 0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
            try { if (!instrument.getUiAutomation().injectInputEvent(event, true)) throw new AssertionError("Input injection failed"); }
            finally { event.recycle(); }
        }
        void move(double seconds) {
            double radius = 52 + 16 * Math.sin(seconds * 1.6);
            double x = bounds.exactCenterX() + 55 * Math.sin(seconds * 0.7);
            double y = bounds.exactCenterY() + 38 * Math.cos(seconds * 0.9);
            for (int i = 0; i < 2; i++) { coordinates[i].x = (float) (x + (i == 0 ? -radius : radius)); coordinates[i].y = (float) y; }
            if (!active) {
                downTime = SystemClock.uptimeMillis(); event(MotionEvent.ACTION_DOWN, 1); active = true;
                event(MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2);
            }
            event(MotionEvent.ACTION_MOVE, 2); moves++;
        }
        void stop() {
            if (active) { event(MotionEvent.ACTION_CANCEL, 2); active = false; }
        }
    }

    public static JSONObject collect(Instrumentation instrument, MainActivity activity, String sceneName, String owner) throws Exception {
        partialEvidence = null;
        if (!java.util.Arrays.asList("real", "100", "500").contains(sceneName)) throw new AssertionError("Unsupported scene");
        if (Settings.System.getFloat(activity.getContentResolver(), Settings.System.FONT_SCALE, 1) != 1 ||
            Settings.Global.getFloat(activity.getContentResolver(), Settings.Global.ANIMATOR_DURATION_SCALE, 1) != 1 ||
            Settings.Secure.getInt(activity.getContentResolver(), Settings.Secure.ACCESSIBILITY_ENABLED, 0) != 0)
            throw new AssertionError("Restore fixed profiling settings first");
        PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
        int startThermal = power.getCurrentThermalStatus();
        if (startThermal > PowerManager.THERMAL_STATUS_LIGHT) throw new AssertionError("Thermal precondition not met");
        float refresh = activity.getDisplay().getRefreshRate();
        if (Math.abs(refresh - 60) > 0.5) throw new AssertionError("60Hz required");
        JSONArray scene = "real".equals(sceneName) ? real(activity, owner) : synthetic(Integer.parseInt(sceneName));
        List<WorldNodeDto> nodes = decode(scene);
        String sceneHash = sha(scene.toString());
        ComposeView[] view = new ComposeView[1];
        instrument.runOnMainSync(() -> { try { view[0] = present(activity, nodes); } catch (Exception e) { throw new AssertionError(e); } });
        instrument.waitForIdleSync();
        AccessibilityNodeInfo canvas = find(instrument.getUiAutomation().getRootInActiveWindow(), FOREST, false);
        if (canvas == null || !canvas.isVisibleToUser()) throw new AssertionError("Visible production forest required");
        Rect bounds = new Rect(); canvas.getBoundsInScreen(bounds);
        if (bounds.width() <= 0 || bounds.height() <= 0) throw new AssertionError("Invalid forest viewport");
        HandlerThread samplesThread = new HandlerThread("m706-frame-metrics"); samplesThread.start();
        ArrayList<JSONObject> samples = new ArrayList<>();
        AtomicLong start = new AtomicLong(Long.MAX_VALUE), end = new AtomicLong(Long.MAX_VALUE), lost = new AtomicLong();
        AtomicLong previousCallback = new AtomicLong(Long.MIN_VALUE);
        CountDownLatch tailDelivered = new CountDownLatch(1);
        Window.OnFrameMetricsAvailableListener listener = (window, metrics, dropped) -> {
            long timestamp = metrics.getMetric(FrameMetrics.INTENDED_VSYNC_TIMESTAMP);
            long previous = previousCallback.getAndSet(timestamp);
            // A tail callback can report drops belonging to the last measured frames.
            // Count conservatively when its delivery interval overlaps the window.
            if (timestamp >= start.get() && previous < end.get()) lost.addAndGet(dropped);
            if (end.get() != Long.MAX_VALUE && timestamp >= end.get()) tailDelivered.countDown();
            if (timestamp >= start.get() && timestamp < end.get()) {
                synchronized (samples) {
                    if (samples.size() >= 4096) { lost.incrementAndGet(); return; }
                    try { samples.add(new JSONObject().put("intended_vsync_ns", timestamp)
                        .put("total_duration_ns", metrics.getMetric(FrameMetrics.TOTAL_DURATION))
                        .put("deadline_ns", metrics.getMetric(FrameMetrics.DEADLINE))
                        .put("first_draw", metrics.getMetric(FrameMetrics.FIRST_DRAW_FRAME))); }
                    catch (Exception failure) { lost.incrementAndGet(); }
                }
            }
        };
        instrument.runOnMainSync(() -> activity.getWindow().addOnFrameMetricsAvailableListener(listener, new Handler(samplesThread.getLooper())));
        Gesture gesture = new Gesture(instrument, bounds);
        JSONArray actions = new JSONArray();
        boolean marker = false;
        boolean listenerRemoved = false;
        try {
            long warm = System.nanoTime();
            while (System.nanoTime() - warm < 5 * SECOND) { gesture.move((System.nanoTime() - warm) / 1e9); SystemClock.sleep(16); }
            gesture.stop();
            if (!Trace.isEnabled()) throw new AssertionError("Perfetto app tracing must be active");
            long measurement = System.nanoTime();
            start.set(measurement); end.set(measurement + 20 * SECOND);
            Trace.beginSection("M706.Measure"); marker = true;
            boolean reset = false, selected = false, grown = false, corrected = false;
            while (System.nanoTime() < end.get()) {
                long elapsed = System.nanoTime() - measurement;
                if (!reset && elapsed >= 5 * SECOND) {
                    gesture.stop(); click(instrument, "Reset view", false); reset = true;
                    actions.put(new JSONObject().put("action", "reset").put("elapsed_ns", elapsed));
                }
                if (!selected && elapsed >= 10 * SECOND) {
                    gesture.stop(); click(instrument, "Tree ", true); selected = true;
                    actions.put(new JSONObject().put("action", "selection").put("elapsed_ns", elapsed));
                }
                if (!"real".equals(sceneName) && ((!grown && elapsed >= 15 * SECOND) || (!corrected && elapsed >= 17 * SECOND))) {
                    boolean correction = grown;
                    // Same authoritative fixture object/pins/seed; only growth and revision change.
                    scene.getJSONObject(0).put("growth_state", correction ? "SPROUT" : "YOUNG");
                    scene.getJSONObject(0).put("revision", correction ? 3 : 2);
                    List<WorldNodeDto> changed = decode(scene);
                    instrument.runOnMainSync(() -> content(view[0], changed));
                    if (correction) corrected = true; else grown = true;
                    actions.put(new JSONObject().put("action", correction ? "correction" : "growth").put("elapsed_ns", elapsed));
                }
                gesture.move(elapsed / 1e9); SystemClock.sleep(16);
            }
            Trace.endSection(); marker = false;
            gesture.stop();
            // Force an unmeasured sentinel frame to report any trailing drops,
            // then detach and stop the callback thread before freezing its data.
            instrument.runOnMainSync(() -> activity.getWindow().getDecorView().invalidate());
            if (!tailDelivered.await(5, TimeUnit.SECONDS)) throw new AssertionError("FrameMetrics tail not delivered");
            instrument.runOnMainSync(() -> activity.getWindow().removeOnFrameMetricsAvailableListener(listener));
            listenerRemoved = true;
            samplesThread.quitSafely(); samplesThread.join(2000);
            if (samplesThread.isAlive()) throw new AssertionError("FrameMetrics collector did not quiesce");
            JSONArray population;
            synchronized (samples) { population = new JSONArray(samples); }
            AccessibilityNodeInfo selectedNode = find(instrument.getUiAutomation().getRootInActiveWindow(), "Tree ", true);
            boolean selectionObserved = selectedNode != null && String.valueOf(selectedNode.getText()).contains("selected");
            if (!selectionObserved) throw new AssertionError("Selection state was not observed");
            return new JSONObject().put("scene", sceneName).put("node_count", scene.length()).put("scene_sha256", sceneHash)
                .put("samples", population).put("lost_samples", lost.get()).put("refresh_rate_hz", refresh)
                .put("measurement_start_monotonic_ns", start.get()).put("measurement_end_monotonic_ns", end.get())
                .put("start_thermal_status", startThermal).put("end_thermal_status", power.getCurrentThermalStatus())
                .put("actions", actions).put("injected_motion_count", gesture.moves)
                .put("selection_observed", selectionObserved)
                .put("framework_sample_population", "INTENDED_VSYNC_TIMESTAMP in fixed 20s window; first draws included")
                .put("performance_grade", "NOT GRADED: pinned external extractor required");
        } finally {
            try {
                if (marker) Trace.endSection();
                gesture.stop();
            } finally {
                try {
                    if (!listenerRemoved) instrument.runOnMainSync(() -> activity.getWindow().removeOnFrameMetricsAvailableListener(listener));
                } finally {
                    samplesThread.quitSafely(); samplesThread.join(2000);
                    synchronized (samples) {
                        partialEvidence = new JSONObject().put("scene", sceneName).put("scene_sha256", sceneHash)
                            .put("samples", new JSONArray(samples)).put("lost_samples", lost.get())
                            .put("collection_complete", false).put("callback_thread_stopped", !samplesThread.isAlive())
                            .put("performance_grade", "NOT RUN: incomplete collection evidence only").toString();
                    }
                    if (samplesThread.isAlive()) throw new AssertionError("FrameMetrics collector did not stop");
                }
            }
        }
    }
}

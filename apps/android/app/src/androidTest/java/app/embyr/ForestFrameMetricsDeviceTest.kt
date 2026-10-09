package app.embyr

import android.os.*
import android.view.Choreographer
import android.view.FrameMetrics
import android.view.Window
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import app.embyr.core.model.WorldNodeDto
import app.embyr.feature.world.*
import java.security.MessageDigest
import java.util.Collections
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Synthetic debug renderer measurements in the verification UID; no hosted data or app commands. */
class ForestFrameMetricsDeviceTest {
    @Test fun hundredNodes() { benchmark(100) }
    @Test fun fiveHundredNodes() { benchmark(500) }
    private fun benchmark(count: Int) {
        require(BuildConfig.DEBUG)
        require(Build.VERSION.SDK_INT >= 31)
        val instrument = InstrumentationRegistry.getInstrumentation()
        require(instrument.targetContext.packageName == "app.embyr.verification") { "Benchmarks require the isolated verification build" }
        val nodes = (0 until count).map { i ->
            val seed = MessageDigest.getInstance("SHA-256").digest("m705-synthetic-$i".toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
            WorldNodeDto("%08x-0000-4000-8000-000000000001".format(Locale.US,i+1),"%08x-0000-4000-8000-000000000002".format(Locale.US,i+1),1,"00000000-0000-4000-8000-000000000003",
                (i%25+0.5)/25.0,(i/25+0.5)/ceil(count/25.0),0,"branching_tree",seed,listOf("SEED","SPROUT","YOUNG")[i%3],i+1L)
        }
        val trees = ForestGeometry.painterOrder(nodes).map { ForestGeometry.tree(it) }
        val scene = ForestGeometry.scene(trees)
        val camera = mutableStateOf(ForestGeometry.defaultCamera(scene))
        val measuring = AtomicBoolean(false); val running = AtomicBoolean(true)
        val listenerAttached = AtomicBoolean(false)
        val durations = Collections.synchronizedList(mutableListOf<Long>())
        val deadlines = Collections.synchronizedList(mutableListOf<Long>())
        val dropped = AtomicLong(0); var refresh = 0f
        val handlerThread = HandlerThread("m705-frame-metrics").apply { start() }
        val listener = Window.OnFrameMetricsAvailableListener { _, metrics, missed ->
            if (measuring.get() && metrics.getMetric(FrameMetrics.FIRST_DRAW_FRAME) == 0L) {
                durations.add(metrics.getMetric(FrameMetrics.TOTAL_DURATION)); deadlines.add(metrics.getMetric(FrameMetrics.DEADLINE)); dropped.addAndGet(missed.toLong())
            }
        }
        var callback: Choreographer.FrameCallback? = null
        var start = 0L
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        try {
            scenario.onActivity { activity ->
                refresh = activity.display!!.refreshRate
                start = SystemClock.elapsedRealtimeNanos()
                activity.setContent { ForestCanvas(trees,scene,camera.value,null,Modifier.fillMaxSize()) }
                activity.window.addOnFrameMetricsAvailableListener(listener,Handler(handlerThread.looper))
                listenerAttached.set(true)
                callback = object : Choreographer.FrameCallback {
                    override fun doFrame(frameTimeNanos: Long) {
                        if(!running.get()) return
                        val seconds = (SystemClock.elapsedRealtimeNanos()-start)/1e9
                        // Identical deterministic trajectory for both scene sizes; pan and zoom every frame.
                        val zoom = 2.0 + 0.7*sin(seconds*0.8)
                        camera.value = ForestGeometry.constrain(ForestCamera(ForestPoint(512+160*sin(seconds*0.9),512+160*cos(seconds*0.7)),zoom),scene,activity.window.decorView.width.toDouble(),activity.window.decorView.height.toDouble())
                        Choreographer.getInstance().postFrameCallback(this)
                    }
                }
                Choreographer.getInstance().postFrameCallback(callback!!)
            }
            SystemClock.sleep(2000)
            val measuredStart = SystemClock.elapsedRealtimeNanos()
            measuring.set(true); SystemClock.sleep(20000); measuring.set(false)
            val measuredNs = SystemClock.elapsedRealtimeNanos()-measuredStart
            // Quiesce before copying paired frame metrics.
            scenario.onActivity { activity -> running.set(false); callback?.let { Choreographer.getInstance().removeFrameCallback(it) }; if(listenerAttached.getAndSet(false)) activity.window.removeOnFrameMetricsAvailableListener(listener) }
            handlerThread.quitSafely(); handlerThread.join(3000)
            val sorted = durations.toList().sorted()
            assertTrue("FrameMetrics produced too few samples",sorted.size >= 100)
            assertEquals(durations.size,deadlines.size)
            assertTrue("Required frame deadlines unavailable",deadlines.all { it > 0 })
            assertTrue("Frame durations unavailable",durations.all { it >= 0 })
            fun percentile(p: Double) = sorted[(ceil(p*sorted.size).toInt()-1).coerceIn(0,sorted.lastIndex)]/1e6
            val misses = durations.indices.count { durations[it] >= deadlines[it] && deadlines[it] > 0 }
            val report = JSONObject().put("scene_nodes",count).put("build_mode","synthetic debug verification")
                .put("source", "framework FrameMetrics TOTAL_DURATION / DEADLINE")
                .put("warmup_seconds",2).put("measurement_seconds",measuredNs/1e9).put("refresh_rate_hz",refresh)
                .put("frame_count",sorted.size).put("p50_ms",percentile(0.50)).put("p95_ms",percentile(0.95)).put("p99_ms",percentile(0.99))
                .put("deadline_misses",misses).put("deadline_miss_percent",100.0*misses/sorted.size).put("dropped_samples",dropped.get())
                .put("release_performance_guarantee",false)
            instrument.targetContext.filesDir.resolve("m705-benchmark-$count.json").writeText(report.toString(2))
        } finally {
            measuring.set(false); running.set(false)
            scenario.onActivity { activity -> callback?.let { Choreographer.getInstance().removeFrameCallback(it) }; if(listenerAttached.getAndSet(false)) activity.window.removeOnFrameMetricsAvailableListener(listener) }
            scenario.close(); handlerThread.quitSafely()
        }
    }
}

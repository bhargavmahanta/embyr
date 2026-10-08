package app.embyr.feature.world

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.ui.platform.testTag
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import app.embyr.core.model.WorldNodeDto
import kotlinx.coroutines.launch

fun forestMotionAllowed(durationScale: Float) = durationScale > 0f

@Composable
private fun rememberForestMotion(): Boolean {
    val resolver = LocalContext.current.contentResolver
    fun enabled() = forestMotionAllowed(Settings.Global.getFloat(resolver,Settings.Global.ANIMATOR_DURATION_SCALE,1f))
    var allowed by remember { mutableStateOf(enabled()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { allowed = enabled() }
        }
        resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE),false,observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return allowed
}

/** No inferred growth: existing nodes transition only when the authoritative category changes. */
@Composable
fun NativeForest(nodes: List<WorldNodeDto>, names: Map<Pair<String,Long>,String>, modifier: Modifier = Modifier, showForest: Boolean = true, header: @Composable () -> Unit = {}) {
    val allowMotion = rememberForestMotion()
    val ordered = remember(nodes) { ForestGeometry.painterOrder(nodes) }
    val growths = remember { mutableStateMapOf<String,Double>() }
    val targets = remember(ordered) { ordered.associate { it.id to ForestGeometry.growthSize(it.growthState) } }
    LaunchedEffect(targets,allowMotion) {
        growths.keys.toList().filter { it !in targets }.forEach { growths.remove(it) }
        targets.forEach { (id,target) ->
            val previous = growths[id]
            if (previous == null || !allowMotion) growths[id] = target
            else if (previous != target) launch {
                Animatable(previous.toFloat()).animateTo(target.toFloat(),tween(220)) { growths[id] = value.toDouble() }
            }
        }
    }
    val trees by remember(ordered) { derivedStateOf {
        ordered.map { ForestGeometry.tree(it,growths[it.id] ?: ForestGeometry.growthSize(it.growthState)) }
    } }
    // Fit uses the final maximum silhouette, so a growth transition does not move the camera.
    val scene = remember(ordered) { ForestGeometry.scene(ordered.map { ForestGeometry.tree(it,1.0) }) }
    var camera by remember { mutableStateOf(ForestGeometry.defaultCamera(scene)) }
    var size by remember { mutableStateOf(IntSize.Zero) }
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(scene,size) {
        camera = ForestGeometry.constrain(camera,scene,size.width.toDouble(),size.height.toDouble())
        if (selectedId !in nodes.map { it.id }) selectedId = null
    }
    val touchPixels = with(LocalDensity.current) { 48.dp.toPx().toDouble() }
    LazyColumn(modifier.testTag("forest"),verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item(key = "header") { header() }
        if(showForest) {
        item(key = "canvas") { ForestCanvas(trees,scene,camera,selectedId,Modifier.fillMaxWidth().height(320.dp).onSizeChanged { size = it }
            .semantics { contentDescription = "Forest map. Select a tree using the list below, or pan and pinch to zoom." }
            .pointerInput(scene,size) {
                detectTransformGestures { centroid,pan,zoom,_ ->
                    camera = ForestGeometry.gesture(camera,scene,size.width.toDouble(),size.height.toDouble(),ForestPoint(centroid.x.toDouble(),centroid.y.toDouble()),ForestPoint(pan.x.toDouble(),pan.y.toDouble()),zoom.toDouble())
                }
            }.pointerInput(trees,scene,size) {
                detectTapGestures { point -> selectedId = ForestGeometry.hit(trees,ForestPoint(point.x.toDouble(),point.y.toDouble()),camera,scene,size.width.toDouble(),size.height.toDouble(),touchPixels) }
            }) }
        // Wrapped controls stay reachable at large font sizes.
        item(key = "reset") { OutlinedButton(onClick = { camera = ForestGeometry.defaultCamera(scene) }) { Text("Reset view") } }
        item(key = "zoom-in") { OutlinedButton(onClick = { camera = ForestGeometry.constrain(camera.copy(zoom = camera.zoom*1.5),scene,size.width.toDouble(),size.height.toDouble()) }, enabled = camera.zoom < 8) { Text("Zoom in") } }
        item(key = "zoom-out") { OutlinedButton(onClick = { camera = ForestGeometry.constrain(camera.copy(zoom = camera.zoom/1.5),scene,size.width.toDouble(),size.height.toDouble()) }, enabled = camera.zoom > 1) { Text("Zoom out") } }
        item(key = "facts") { Text("${nodes.size} trees. Growth reflects recorded encounters, reflections or completion, and recognition evidence.") }
        items(ordered,key = { it.id }) { node ->
            val label = names[node.entityId to node.entityVersion] ?: "Tree ${node.id} — name unavailable"
            OutlinedButton(onClick = {
                selectedId = node.id
                camera = ForestGeometry.constrain(ForestCamera(ForestGeometry.tree(node).anchor, maxOf(2.0,camera.zoom)),scene,size.width.toDouble(),size.height.toDouble())
            }, modifier = Modifier.fillMaxWidth().semantics { selected = selectedId == node.id }) {
                Text("$label · ${node.growthState.lowercase()}${if(selectedId == node.id) " · selected" else ""}")
            }
        }
        }
    }
}

/** Shared renderer is also exercised by synthetic physical FrameMetrics benchmarks. */
@Composable
fun ForestCanvas(trees: List<TreeGeometry>, scene: ForestBounds, camera: ForestCamera, selectedId: String?, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        drawRect(Color(0xffeef2e9))
        val width = size.width.toDouble(); val height = size.height.toDouble()
        val scale = ForestGeometry.fit(scene,width,height)*camera.zoom
        fun screen(point: ForestPoint): Offset {
            val transformed = ForestGeometry.toScreen(point,camera,scene,width,height)
            return Offset(transformed.x.toFloat(),transformed.y.toFloat())
        }
        ForestGeometry.visible(trees,camera,scene,width,height).forEach { tree ->
            tree.branches.forEach { drawLine(Color(0xff6c7862),screen(it.from),screen(it.to),(it.width*scale).toFloat()) }
            tree.circles.forEach { drawCircle(Color(0xff91ac82), (it.radius*scale).toFloat(),screen(it.center)) }
            if (selectedId == tree.id) drawCircle(Color(0xff365f4a), (14*scale).toFloat().coerceAtLeast(5f),screen(tree.anchor),style = androidx.compose.ui.graphics.drawscope.Stroke(2.dp.toPx()))
        }
    }
}

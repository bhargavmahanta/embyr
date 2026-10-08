package app.embyr.feature.world

import app.embyr.core.model.WorldNodeDto
import kotlin.math.*

data class ForestPoint(val x: Double, val y: Double)
data class ForestBounds(val left: Double, val top: Double, val right: Double, val bottom: Double) {
    val width get() = right-left
    val height get() = bottom-top
    fun intersects(other: ForestBounds) = right >= other.left && left <= other.right && bottom >= other.top && top <= other.bottom
    fun expand(distance: Double) = ForestBounds(left-distance,top-distance,right+distance,bottom+distance)
}
data class ForestCircle(val center: ForestPoint, val radius: Double)
data class ForestBranch(val from: ForestPoint, val to: ForestPoint, val width: Double)
data class TreeGeometry(val id: String, val anchor: ForestPoint, val circles: List<ForestCircle>, val branches: List<ForestBranch>, val bounds: ForestBounds) {
    fun contains(point: ForestPoint, tolerance: Double): Boolean = circles.any { hypot(point.x-it.center.x,point.y-it.center.y) <= it.radius+tolerance } || branches.any {
        val dx = it.to.x-it.from.x; val dy = it.to.y-it.from.y
        val length = dx*dx+dy*dy
        val t = if (length == 0.0) 0.0 else (((point.x-it.from.x)*dx+(point.y-it.from.y)*dy)/length).coerceIn(0.0,1.0)
        hypot(point.x-it.from.x-t*dx,point.y-it.from.y-t*dy) <= it.width/2+tolerance
    }
}
data class ForestCamera(val center: ForestPoint, val zoom: Double = 1.0)

/** Drawing, culling and picking consume these same primitives and transform. */
object ForestGeometry {
    fun growthSize(state: String) = when(state) { "SEED" -> 0.25; "SPROUT" -> 0.6; "YOUNG" -> 1.0; else -> throw IllegalArgumentException("Unknown growth") }
    fun tree(node: WorldNodeDto, growth: Double = growthSize(node.growthState)): TreeGeometry {
        val anchor = ForestPoint(node.logicalX*1024, node.logicalY*1024)
        val height = 112*growth
        val radius = 28*growth
        val tilt = (node.visualSeed.take(2).toInt(16)/255.0-0.5)*12*growth
        val crown = ForestPoint(anchor.x+tilt,anchor.y-height)
        val circles = listOf(
            ForestCircle(crown,radius),
            ForestCircle(ForestPoint(crown.x-radius*0.6,crown.y+radius*0.45),radius*0.75),
            ForestCircle(ForestPoint(crown.x+radius*0.65,crown.y+radius*0.35),radius*0.7),
        )
        val branches = listOf(
            ForestBranch(anchor,crown,4.0*growth+1.0),
            ForestBranch(ForestPoint(anchor.x+tilt*0.6,anchor.y-height*0.6),circles[1].center,2.0*growth+1.0),
            ForestBranch(ForestPoint(anchor.x+tilt*0.7,anchor.y-height*0.7),circles[2].center,2.0*growth+1.0),
        )
        val bounds = ForestBounds(
            min(anchor.x-4,circles.minOf { it.center.x-it.radius }), circles.minOf { it.center.y-it.radius },
            max(anchor.x+4,circles.maxOf { it.center.x+it.radius }), anchor.y+4,
        )
        return TreeGeometry(node.id,anchor,circles,branches,bounds)
    }
    fun painterOrder(nodes: List<WorldNodeDto>): List<WorldNodeDto> = nodes.sortedWith(compareBy<WorldNodeDto> { it.logicalY }.thenBy { it.id })
    fun scene(trees: List<TreeGeometry>) = ForestBounds(
        min(0.0, trees.minOfOrNull { it.bounds.left } ?: 0.0), min(0.0,trees.minOfOrNull { it.bounds.top } ?: 0.0),
        max(1024.0,trees.maxOfOrNull { it.bounds.right } ?: 1024.0), max(1024.0,trees.maxOfOrNull { it.bounds.bottom } ?: 1024.0),
    )
    fun fit(scene: ForestBounds, width: Double, height: Double): Double = min(width/scene.width,height/scene.height).coerceAtLeast(0.0001)*0.92
    fun defaultCamera(scene: ForestBounds) = ForestCamera(ForestPoint((scene.left+scene.right)/2,(scene.top+scene.bottom)/2))
    fun constrain(camera: ForestCamera, scene: ForestBounds, width: Double, height: Double): ForestCamera {
        val zoom = camera.zoom.coerceIn(1.0,8.0)
        val scale = fit(scene,width,height)*zoom
        val halfWidth = width/(2*scale); val halfHeight = height/(2*scale)
        fun axis(value: Double, low: Double, high: Double, half: Double) = if (2*half >= high-low) (low+high)/2 else value.coerceIn(low+half,high-half)
        return ForestCamera(ForestPoint(axis(camera.center.x,scene.left,scene.right,halfWidth),axis(camera.center.y,scene.top,scene.bottom,halfHeight)),zoom)
    }
    fun toScreen(point: ForestPoint, camera: ForestCamera, scene: ForestBounds, width: Double, height: Double): ForestPoint {
        val scale = fit(scene,width,height)*camera.zoom
        return ForestPoint(width/2+(point.x-camera.center.x)*scale,height/2+(point.y-camera.center.y)*scale)
    }
    fun toWorld(point: ForestPoint, camera: ForestCamera, scene: ForestBounds, width: Double, height: Double): ForestPoint {
        val scale = fit(scene,width,height)*camera.zoom
        return ForestPoint(camera.center.x+(point.x-width/2)/scale,camera.center.y+(point.y-height/2)/scale)
    }
    fun gesture(camera: ForestCamera, scene: ForestBounds, width: Double, height: Double, centroid: ForestPoint, pan: ForestPoint, zoomChange: Double): ForestCamera {
        val oldAnchor = toWorld(centroid,camera,scene,width,height)
        val zoom = (camera.zoom*zoomChange).coerceIn(1.0,8.0)
        val scale = fit(scene,width,height)*zoom
        val center = ForestPoint(oldAnchor.x-(centroid.x-width/2+pan.x)/scale,oldAnchor.y-(centroid.y-height/2+pan.y)/scale)
        return constrain(ForestCamera(center,zoom),scene,width,height)
    }
    fun viewport(camera: ForestCamera, scene: ForestBounds, width: Double, height: Double): ForestBounds {
        val a = toWorld(ForestPoint(0.0,0.0),camera,scene,width,height)
        val b = toWorld(ForestPoint(width,height),camera,scene,width,height)
        return ForestBounds(a.x,a.y,b.x,b.y)
    }
    fun visible(trees: List<TreeGeometry>, camera: ForestCamera, scene: ForestBounds, width: Double, height: Double): List<TreeGeometry> {
        val viewport = viewport(camera,scene,width,height)
        return trees.filter { it.bounds.intersects(viewport) }
    }
    fun hit(trees: List<TreeGeometry>, screen: ForestPoint, camera: ForestCamera, scene: ForestBounds, width: Double, height: Double, minimumTouchPixels: Double): String? {
        val point = toWorld(screen,camera,scene,width,height)
        val tolerance = minimumTouchPixels/(2*fit(scene,width,height)*camera.zoom)
        return trees.asReversed().firstOrNull { it.bounds.expand(tolerance).intersects(ForestBounds(point.x,point.y,point.x,point.y)) && it.contains(point,tolerance) }?.id
    }
}

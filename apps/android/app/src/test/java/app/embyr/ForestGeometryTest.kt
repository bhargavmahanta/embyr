package app.embyr

import app.embyr.feature.world.*
import org.junit.Assert.*
import org.junit.Test

class ForestGeometryTest {
    private val node = M6Fixtures.world("world_populated").nodes.first()
    @Test fun deterministicShapeAndRoundTripTransforms() {
        val tree = ForestGeometry.tree(node)
        assertEquals(tree,ForestGeometry.tree(node))
        assertEquals(node.logicalX*1024,tree.anchor.x,0.0)
        val scene = ForestGeometry.scene(listOf(tree)); val camera = ForestGeometry.defaultCamera(scene)
        val point = ForestPoint(240.0,730.0)
        val screen = ForestGeometry.toScreen(point,camera,scene,400.0,300.0)
        val recovered = ForestGeometry.toWorld(screen,camera,scene,400.0,300.0)
        assertEquals(point.x,recovered.x,0.000001); assertEquals(point.y,recovered.y,0.000001)
    }
    @Test fun overlapPicksLastPaintedNodeAndOffscreenTreesAreCulled() {
        val other = node.copy(id = "ffffffff-ffff-ffff-ffff-ffffffffffff")
        val trees = ForestGeometry.painterOrder(listOf(other,node)).map { ForestGeometry.tree(it) }
        val scene = ForestGeometry.scene(trees); val camera = ForestGeometry.defaultCamera(scene)
        val screen = ForestGeometry.toScreen(trees.first().circles.first().center,camera,scene,400.0,300.0)
        assertEquals(other.id,ForestGeometry.hit(trees,screen,camera,scene,400.0,300.0,48.0))
        val away = ForestGeometry.constrain(ForestCamera(ForestPoint(0.0,0.0),8.0),scene,400.0,300.0)
        assertTrue(ForestGeometry.visible(trees,away,scene,400.0,300.0).isEmpty())
    }
    @Test fun cameraBoundsZoomAndGrowthCorrectionShareGeometry() {
        val tree = ForestGeometry.tree(node); val scene = ForestGeometry.scene(listOf(tree))
        val capped = ForestGeometry.gesture(ForestGeometry.defaultCamera(scene),scene,400.0,300.0,ForestPoint(200.0,150.0),ForestPoint(1e9,-1e9),50.0)
        assertEquals(8.0,capped.zoom,0.0)
        val visible = ForestGeometry.viewport(capped,scene,400.0,300.0)
        assertTrue(visible.left >= scene.left-0.0001 && visible.bottom <= scene.bottom+0.0001)
        val corrected = ForestGeometry.tree(node.copy(growthState = "SEED"))
        val grown = ForestGeometry.tree(node.copy(growthState = "YOUNG"))
        assertEquals(corrected.anchor,grown.anchor)
        assertTrue(corrected.bounds.height < grown.bounds.height)
    }
}

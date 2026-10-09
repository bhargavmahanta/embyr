package app.embyr

import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import app.embyr.auth.OwnerBinding
import app.embyr.core.model.*
import app.embyr.feature.memory.*
import app.embyr.feature.world.*
import app.embyr.core.storage.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class MemoryWorldComposeTest {
    @get:Rule val compose = createComposeRule()
    @Test fun memorySeparatesCachedFreshnessAndFailedProjectionAndKeepsUnavailableChoice() {
        val summary = MemorySummaryDto("memory-summary/v1",ProjectionDto("learner-projection/v1",1,2,"FAILED"),null,
            listOf(ExplicitInterestDto(MemoryWorldStorageDeviceTest.ENTITY,null,null,"LESS",3,"2026-10-01T00:00:00Z","UNAVAILABLE")),emptyList(),emptyList(),emptyList(),emptyList(),TruncatedDto(false,false,false))
        var back = false
        compose.setContent { MaterialTheme { MemoryScreen(MemoryUiState(OwnerBinding("a",1),MemoryRead(summary,1000,false,null,emptyList())),{},{ _,_ -> },{},{},{ back = true }) } }
        compose.onNodeWithText("Projection: FAILED").assertIsDisplayed()
        compose.onNodeWithText("Saved copy",substring = true).assertIsDisplayed()
        compose.onNodeWithText("Interest ${MemoryWorldStorageDeviceTest.ENTITY} — unavailable").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Back to entry").performScrollTo().performClick()
        assertTrue(back)
    }
    @Test fun worldControlsAndTreeListRemainAccessibleWithLargeText() {
        val node = WorldNodeDto(MemoryWorldStorageDeviceTest.NODE,MemoryWorldStorageDeviceTest.ENTITY,1,MemoryWorldStorageDeviceTest.REGION,0.5,0.5,0,"branching_tree","b".repeat(64),"SPROUT",2)
        val snapshot = WorldSnapshotDto(2,1,"a".repeat(64),listOf(WorldRegionDto(MemoryWorldStorageDeviceTest.REGION,"discovery",null,0,0,1,1,"grove")),listOf(node),emptyList(),emptyList())
        compose.setContent { androidx.compose.runtime.CompositionLocalProvider(androidx.compose.ui.platform.LocalDensity provides androidx.compose.ui.unit.Density(1f,2f)) {
            MaterialTheme { WorldScreen(WorldUiState(OwnerBinding("a",1),WorldRead(CachedWorld(snapshot,WorldStamp(2,1))),mapOf((node.entityId to 1L) to "Reviewed topic")),{},{}) }
        } }
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Reset view"))
        compose.onNodeWithText("Reset view").assertIsDisplayed().performClick()
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Zoom in"))
        compose.onNodeWithText("Zoom in").performClick()
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Reviewed topic",substring = true))
        compose.onNodeWithText("Reviewed topic",substring = true).performClick()
        compose.onNodeWithText("selected",substring = true).assertIsDisplayed()
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Back to entry"))
        compose.onNodeWithText("Back to entry").assertIsDisplayed()
    }
    @Test fun unresolvedIntentsIdentifyTheirTargetsEvenWithoutSummary() {
        val first = InterestOperationEntity("first","a",MemoryWorldStorageDeviceTest.ENTITY,1,"LESS","{}".toByteArray(),1000)
        val second = first.copy(id = "second",entityId = MemoryWorldStorageDeviceTest.REGION)
        compose.setContent { MaterialTheme { MemoryScreen(MemoryUiState(OwnerBinding("a",1),MemoryRead(null,null,false,null,listOf(first,second))),{},{ _,_ -> },{},{},{}) } }
        compose.onNodeWithText("Interest reference: ${first.entityId}").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Interest reference: ${second.entityId}").performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("Apply saved intent to current version").fetchSemanticsNodes().let { assertEquals(2,it.size) }
        compose.onAllNodesWithText("Apply saved intent to current version")[1].assertIsNotEnabled()
    }

    @Test fun fiveHundredTreeListComposesVisibleRowsAndReachesLastSelection() {
        val nodes = (1..500).map { i -> WorldNodeDto("%08x-0000-4000-8000-000000000001".format(i),"%08x-0000-4000-8000-000000000002".format(i),1,MemoryWorldStorageDeviceTest.REGION,(i%25)/25.0,(i/25)/20.0,0,"branching_tree","b".repeat(64),"SEED",i.toLong()) }
        val names = nodes.mapIndexed { i,node -> (node.entityId to 1L) to "Topic ${i+1}" }.toMap()
        var virtualized by androidx.compose.runtime.mutableStateOf(false)
        compose.setContent { MaterialTheme {
            if(virtualized) NativeForest(nodes,names,androidx.compose.ui.Modifier)
            else androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.verticalScroll(androidx.compose.foundation.rememberScrollState())) {
                // Retained eager-list baseline: all 500 Material rows compose before viewport culling.
                nodes.forEachIndexed { i,_ -> androidx.compose.material3.OutlinedButton(onClick = {}) { androidx.compose.material3.Text("Topic ${i+1}") } }
            }
        } }
        val baselineCount = compose.onAllNodes(hasText("Topic",substring = true) and hasClickAction()).fetchSemanticsNodes().size
        assertEquals(500,baselineCount)
        compose.runOnIdle { virtualized = true }
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Topic 1",substring = true))
        val count = compose.onAllNodes(hasText("Topic",substring = true) and hasClickAction()).fetchSemanticsNodes().size
        assertTrue("Only visible list rows should compose",count in 1..15)
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext.filesDir.resolve("m705-list-composition.json").writeText("{\"synthetic_nodes\":500,\"eager_semantic_rows\":$baselineCount,\"lazy_semantic_rows\":$count,\"metric\":\"composed selectable list rows; not frame duration\"}")
        val phase = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext.filesDir.resolve("m705-list-phase.txt")
        phase.writeText("before-last-scroll")
        compose.onNodeWithTag("forest").performScrollToNode(hasText("Topic 500",substring = true))
        phase.writeText("after-last-scroll")
        compose.onNodeWithText("Topic 500",substring = true).performClick()
        phase.writeText("after-selection")
        compose.onNodeWithText("Topic 500",substring = true).assertIsSelected()
        phase.writeText("complete")
    }

    @Test fun reducedMotionPolicyDisablesGrowthTransitions() {
        assertFalse(forestMotionAllowed(0f)); assertTrue(forestMotionAllowed(1f))
    }
}

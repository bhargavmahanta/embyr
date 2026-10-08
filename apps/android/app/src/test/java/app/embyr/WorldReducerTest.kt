package app.embyr

import app.embyr.core.model.*
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class WorldReducerTest {
    private val json = Json
    private val examples = run {
        val root = generateSequence(File(System.getProperty("user.dir")).canonicalFile) { it.parentFile }
            .first { File(it, "docs/api/fixtures/m6-v1.json").isFile }
        json.parseToJsonElement(File(root, "docs/api/fixtures/m6-v1.json").readText()).jsonObject.getValue("public_examples").jsonObject
    }
    private fun snapshot(name: String) = json.decodeFromJsonElement(WorldSnapshotDto.serializer(), examples.getValue(name))
    private fun page(name: String) = json.decodeFromJsonElement(WorldDeltaPageDto.serializer(), examples.getValue(name))
    @Test fun committedPagesEqualPublicSnapshot() {
        val first = WorldReducer.apply(snapshot("world_empty"), page("delta_page_1"))
        assertEquals(2L, first.revision)
        assertEquals(snapshot("world_populated"), WorldReducer.apply(first, page("delta_page_2")))
    }
    @Test fun rejectsGapAndChangedImmutablePin() {
        val first = WorldReducer.apply(snapshot("world_empty"), page("delta_page_1"))
        assertThrows(IllegalArgumentException::class.java) { WorldReducer.apply(first, page("delta_page_1")) }
        val next = page("delta_page_2")
        val changes = next.changes.toMutableList()
        val growth = changes.last()
        val node = (growth.payload as NodePayloadDto).`object`
        changes[changes.lastIndex] = growth.copy(payload = NodePayloadDto("world-delta/v1", node.copy(entityVersion = node.entityVersion + 1)))
        assertThrows(IllegalArgumentException::class.java) { WorldReducer.apply(first, next.copy(changes = changes)) }
        assertEquals(2L, first.revision)
    }
}

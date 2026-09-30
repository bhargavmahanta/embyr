package app.embyr

import app.embyr.core.model.AssessmentSessionDto
import app.embyr.core.model.EvaluationRetryDto
import app.embyr.core.model.ExplorationDetailDto
import app.embyr.core.model.MemorySummaryDto
import app.embyr.core.model.WorldDeltaPageDto
import app.embyr.core.model.WorldResyncRequiredDto
import app.embyr.core.model.WorldSnapshotDto
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CanonicalFixtureTest {
    private val json = Json { ignoreUnknownKeys = false }

    private fun repositoryRoot(): File {
        val starting = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        return generateSequence(starting) { it.parentFile }
            .firstOrNull { File(it, "docs/api/fixtures/m6-v1.json").isFile }
            ?: error("Canonical repository fixtures are missing from $starting")
    }

    @Test fun m5ExamplesDecodeAgainstReviewedDtos() {
        val fixture = File(repositoryRoot(), "docs/api/fixtures/learning-lifecycle-v1.json").readText()
        val objectValue = json.parseToJsonElement(fixture).jsonObject
        val exploration = json.decodeFromJsonElement(ExplorationDetailDto.serializer(), objectValue.getValue("exploration"))
        val session = json.decodeFromJsonElement(AssessmentSessionDto.serializer(), objectValue.getValue("session"))
        val retry = json.decodeFromJsonElement(EvaluationRetryDto.serializer(), objectValue.getValue("retry"))
        assertEquals("exploration-lifecycle/v1", exploration.lifecycleContractVersion)
        assertEquals("RECOGNITION", session.interaction.interactionType)
        assertEquals("PENDING", retry.evaluationStatus)
    }

    @Test fun m6PublicExamplesDecodeIndividually() {
        val fixture = File(repositoryRoot(), "docs/api/fixtures/m6-v1.json").readText()
        val examples = json.parseToJsonElement(fixture).jsonObject.getValue("public_examples").jsonObject
        assertEquals(12, examples.size)
        examples.forEach { (name, wrapped) ->
            val wrapper = wrapped.jsonObject
            val value = wrapper["value"] ?: wrapped
            when {
                name.startsWith("memory") -> {
                    val dto = json.decodeFromJsonElement(MemorySummaryDto.serializer(), value)
                    assertEquals("memory-summary/v1", dto.contractVersion)
                }
                name.startsWith("world") -> {
                    val dto = json.decodeFromJsonElement(WorldSnapshotDto.serializer(), value)
                    assertTrue(dto.revision >= 0)
                }
                name.startsWith("delta") -> {
                    val dto = json.decodeFromJsonElement(WorldDeltaPageDto.serializer(), value)
                    assertTrue(dto.currentRevision >= dto.toRevision)
                }
                name.startsWith("resync") -> {
                    val dto = json.decodeFromJsonElement(WorldResyncRequiredDto.serializer(), value)
                    assertEquals("WORLD_RESYNC_REQUIRED", dto.code)
                }
                else -> error("Unreviewed public example: $name")
            }
        }
    }
}

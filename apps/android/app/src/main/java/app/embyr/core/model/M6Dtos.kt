package app.embyr.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.json.JsonContentPolymorphicSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonObject

@Serializable
data class ProjectionDto(
    @SerialName("model_version") val modelVersion: String,
    @SerialName("source_sequence") val sourceSequence: Long,
    @SerialName("source_head_sequence") val sourceHeadSequence: Long,
    val status: String,
)

@Serializable
data class ExplicitInterestDto(
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long?,
    val title: String?,
    val preference: String,
    val version: Long,
    @SerialName("updated_at") val updatedAt: String,
    val availability: String,
)

@Serializable
data class RecentExplorationDto(
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long,
    val title: String,
    @SerialName("started_count") val startedCount: Long,
    @SerialName("returned_count") val returnedCount: Long,
    @SerialName("completed_count") val completedCount: Long,
    @SerialName("latest_activity_at") val latestActivityAt: String,
)

@Serializable
data class RecognitionEvidenceDto(
    @SerialName("objective_id") val objectiveId: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long,
    @SerialName("evidence_count") val evidenceCount: Long,
    @SerialName("support_required") val supportRequired: Boolean,
    @SerialName("last_evidence_at") val lastEvidenceAt: String,
    val summary: String,
)

@Serializable
data class TruncatedDto(
    @SerialName("explicit_interests") val explicitInterests: Boolean,
    @SerialName("recently_explored") val recentlyExplored: Boolean,
    @SerialName("recognition_evidence") val recognitionEvidence: Boolean,
)

@Serializable
data class MemorySummaryDto(
    @SerialName("contract_version") val contractVersion: String,
    val projection: ProjectionDto,
    @SerialName("learning_preferences") val learningPreferences: PreferencesDto?,
    @SerialName("explicit_interests") val explicitInterests: List<ExplicitInterestDto>,
    @SerialName("recently_explored") val recentlyExplored: List<RecentExplorationDto>,
    @SerialName("recognition_evidence") val recognitionEvidence: List<RecognitionEvidenceDto>,
    @SerialName("long_term_interests") val longTermInterests: List<JsonElement>,
    @SerialName("voluntary_revisits") val voluntaryRevisits: List<JsonElement>,
    val truncated: TruncatedDto,
)

@Serializable
data class WorldRegionDto(
    val id: String,
    @SerialName("region_key") val regionKey: String,
    @SerialName("primary_domain_id") val primaryDomainId: String?,
    @SerialName("logical_x") val logicalX: Int,
    @SerialName("logical_y") val logicalY: Int,
    @SerialName("logical_width") val logicalWidth: Int,
    @SerialName("logical_height") val logicalHeight: Int,
    @SerialName("visual_archetype") val visualArchetype: String,
)

@Serializable
data class WorldNodeDto(
    val id: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long,
    @SerialName("region_id") val regionId: String,
    @SerialName("logical_x") val logicalX: Double,
    @SerialName("logical_y") val logicalY: Double,
    val depth: Int,
    @SerialName("visual_archetype") val visualArchetype: String,
    @SerialName("visual_seed") val visualSeed: String,
    @SerialName("growth_state") val growthState: String,
    val revision: Long,
)

@Serializable
data class WorldSnapshotDto(
    val revision: Long,
    @SerialName("layout_version") val layoutVersion: Int,
    @SerialName("generation_seed") val generationSeed: String,
    val regions: List<WorldRegionDto>,
    val nodes: List<WorldNodeDto>,
    val connections: List<JsonElement>,
    val artifacts: List<JsonElement>,
)

@Serializable(with = WorldPayloadSerializer::class)
sealed interface WorldPayloadDto

@Serializable
data class RegionPayloadDto(
    @SerialName("schema_version") val schemaVersion: String,
    val `object`: WorldRegionDto,
) : WorldPayloadDto

@Serializable
data class NodePayloadDto(
    @SerialName("schema_version") val schemaVersion: String,
    val `object`: WorldNodeDto,
) : WorldPayloadDto

object WorldPayloadSerializer : JsonContentPolymorphicSerializer<WorldPayloadDto>(WorldPayloadDto::class) {
    override fun selectDeserializer(element: JsonElement): DeserializationStrategy<WorldPayloadDto> =
        if ("region_key" in element.jsonObject.getValue("object").jsonObject) {
            RegionPayloadDto.serializer()
        } else {
            NodePayloadDto.serializer()
        }
}

@Serializable
data class WorldChangeDto(
    val revision: Long,
    val type: String,
    @SerialName("object_id") val objectId: String,
    val payload: WorldPayloadDto,
)

@Serializable
data class WorldDeltaPageDto(
    @SerialName("from_revision") val fromRevision: Long,
    @SerialName("to_revision") val toRevision: Long,
    @SerialName("current_revision") val currentRevision: Long,
    @SerialName("has_more") val hasMore: Boolean,
    val changes: List<WorldChangeDto>,
)

@Serializable
data class WorldResyncDetailsDto(
    @SerialName("after_revision") val afterRevision: Long,
    @SerialName("current_revision") val currentRevision: Long,
)

@Serializable
data class WorldResyncRequiredDto(
    val type: String,
    val title: String,
    val status: Int,
    val code: String,
    val detail: String,
    @SerialName("request_id") val requestId: String,
    val details: WorldResyncDetailsDto,
)

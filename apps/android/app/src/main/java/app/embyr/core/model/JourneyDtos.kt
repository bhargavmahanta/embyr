package app.embyr.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable data class StarterInterestDto(
    val id: String,
    @SerialName("entity_type") val entityType: String,
    @SerialName("entity_version") val entityVersion: Long,
    val title: String,
    val summary: String,
)

@Serializable data class StarterInterestPageDto(val items: List<StarterInterestDto>)

@Serializable data class OnboardingRequestDto(
    val motivations: List<String> = emptyList(),
    @SerialName("starter_interest_entity_ids") val starterInterestEntityIds: List<String>,
    @SerialName("adventure_preference") val adventurePreference: String = "BALANCED",
    @SerialName("preferred_effort") val preferredEffort: String = "15_20_MIN",
    @SerialName("support_style") val supportStyle: String = "SMALL_HINT",
    @SerialName("practical_opt_in") val practicalOptIn: Boolean = false,
)

@Serializable data class OnboardingResultDto(
    val preferences: PreferencesDto,
    @SerialName("onboarding_completed_at") val onboardingCompletedAt: String,
)

@Serializable data class RecommendationRequestDto(
    val mode: String,
    @SerialName("available_minutes") val availableMinutes: Int? = null,
    @SerialName("practical_context") val practicalContext: JsonObject? = null,
)

@Serializable data class RecommendationDecisionRequestDto(
    val decision: String,
    val reason: String? = null,
)

@Serializable data class SkippedRecommendationDto(
    @SerialName("recommendation_id") val recommendationId: String,
    val decision: String,
)

@Serializable data class AcceptedExplorationDto(
    val id: String,
    val entity: RecommendationEntityDto,
    @SerialName("entity_version") val entityVersion: Long,
    @SerialName("practical_challenge_id") val practicalChallengeId: String?,
    @SerialName("learning_intent") val learningIntent: String,
    val status: String,
    @SerialName("started_at") val startedAt: String,
    @SerialName("returned_at") val returnedAt: String?,
    @SerialName("paused_at") val pausedAt: String?,
    @SerialName("completed_at") val completedAt: String?,
    val version: Long,
)

sealed interface RecommendationDecisionResult {
    data class Accepted(val exploration: AcceptedExplorationDto) : RecommendationDecisionResult
    data class Skipped(val result: SkippedRecommendationDto) : RecommendationDecisionResult
}

@Serializable data class ExplorationListItemDto(
    val id: String,
    @SerialName("recommendation_id") val recommendationId: String?,
    val status: String,
)

@Serializable data class ExplorationPageDto(
    val items: List<ExplorationListItemDto>,
    @SerialName("next_cursor") val nextCursor: String?,
)

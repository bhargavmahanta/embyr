package app.embyr.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class PreferencesDto(
    @SerialName("adventure_preference") val adventurePreference: String,
    @SerialName("preferred_effort") val preferredEffort: String,
    @SerialName("support_style") val supportStyle: String,
    @SerialName("practical_opt_in") val practicalOptIn: Boolean,
    val version: Long,
)

@Serializable
data class ProfileDto(
    val id: String,
    @SerialName("onboarding_completed_at") val onboardingCompletedAt: String?,
    val preferences: PreferencesDto?,
    @SerialName("world_revision") val worldRevision: Long?,
)

@Serializable
data class EntitySummaryDto(
    val id: String,
    @SerialName("entity_version") val entityVersion: Long,
    val title: String,
    val summary: String,
)

@Serializable
data class DeliveryDto(
    @SerialName("content_id") val contentId: String,
    @SerialName("content_version") val contentVersion: Long,
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long,
    @SerialName("objective_id") val objectiveId: String,
    @SerialName("delivery_contract_version") val deliveryContractVersion: String,
    @SerialName("work_prompt") val workPrompt: String,
    @SerialName("effort_guidance") val effortGuidance: String,
    @SerialName("search_nudges") val searchNudges: List<String>,
    @SerialName("reflection_prompt") val reflectionPrompt: String,
)

@Serializable
data class ReflectionDto(
    val id: String,
    @SerialName("exploration_id") val explorationId: String,
    @SerialName("entity_id") val entityId: String,
    val text: String,
    val version: Long,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class AssessmentReferenceDto(val id: String, val status: String)

@Serializable
data class ExplorationDetailDto(
    val id: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("entity_version") val entityVersion: Long,
    @SerialName("recommendation_id") val recommendationId: String?,
    @SerialName("practical_challenge_id") val practicalChallengeId: String?,
    @SerialName("practical_challenge_version_id") val practicalChallengeVersionId: String?,
    @SerialName("learning_intent") val learningIntent: String,
    val status: String,
    @SerialName("started_at") val startedAt: String,
    @SerialName("returned_at") val returnedAt: String?,
    @SerialName("paused_at") val pausedAt: String?,
    @SerialName("completed_at") val completedAt: String?,
    val version: Long,
    @SerialName("lifecycle_contract_version") val lifecycleContractVersion: String,
    val entity: EntitySummaryDto?,
    val delivery: DeliveryDto?,
    val reflection: ReflectionDto?,
    @SerialName("assessment_session") val assessmentSession: AssessmentReferenceDto?,
)

@Serializable
data class AssessmentOptionDto(val id: String, val label: String)

@Serializable
data class InteractionDto(
    val id: String,
    @SerialName("interaction_type") val interactionType: String,
    val prompt: String,
    @SerialName("strategy_version") val strategyVersion: String,
    @SerialName("interaction_contract_version") val interactionContractVersion: String,
    @SerialName("evaluator_version") val evaluatorVersion: String,
    @SerialName("evidence_contract_version") val evidenceContractVersion: String,
    val options: List<AssessmentOptionDto>,
)

@Serializable
data class SupportContentDto(val text: String)

@Serializable
data class SupportDto(val id: String, val level: String, val content: SupportContentDto)

@Serializable
data class EvaluationDto(
    val id: String,
    val status: String,
    val result: String?,
    val confidence: Double?,
    val feedback: String?,
    @SerialName("failure_category") val failureCategory: String?,
    @SerialName("retry_allowed") val retryAllowed: Boolean,
)

@Serializable
data class AssessmentSessionDto(
    val id: String,
    @SerialName("exploration_id") val explorationId: String,
    val status: String,
    @SerialName("confidence_before") val confidenceBefore: String,
    @SerialName("strategy_version") val strategyVersion: String,
    val interaction: InteractionDto,
    @SerialName("delivered_support") val deliveredSupport: List<SupportDto>,
    @SerialName("response_id") val responseId: String?,
    val evaluation: EvaluationDto?,
    @SerialName("evaluation_status") val evaluationStatus: String?,
    val feedback: String?,
    @SerialName("retry_allowed") val retryAllowed: Boolean,
)

@Serializable
data class AnswerAcknowledgmentDto(
    @SerialName("response_id") val responseId: String,
    @SerialName("evaluation_status") val evaluationStatus: String,
    @SerialName("session_status") val sessionStatus: String,
    @SerialName("next_interaction") val nextInteraction: String?,
)

@Serializable
data class EvaluationRetryDto(
    @SerialName("response_id") val responseId: String,
    @SerialName("evaluation_status") val evaluationStatus: String,
    @SerialName("session_status") val sessionStatus: String,
    @SerialName("next_interaction") val nextInteraction: String?,
    @SerialName("evaluation_run_id") val evaluationRunId: String,
)

@Serializable
data class RecommendationDto(
    val id: String,
    @SerialName("target_type") val targetType: String,
    val entity: RecommendationEntityDto,
    @SerialName("practical_challenge") val practicalChallenge: String?,
    val mode: String,
    @SerialName("distance_band") val distanceBand: String,
    val hook: String?,
    val reason: String?,
    @SerialName("presented_at") val presentedAt: String,
)

@Serializable
data class RecommendationEntityDto(val id: String, val title: String)

sealed interface RecommendationResult {
    data object NoResult : RecommendationResult
    data class Found(val recommendation: RecommendationDto) : RecommendationResult
}

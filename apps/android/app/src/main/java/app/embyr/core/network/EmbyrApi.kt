package app.embyr.core.network

import app.embyr.core.model.AnswerAcknowledgmentDto
import app.embyr.core.model.ProfileDto
import app.embyr.core.model.StarterInterestPageDto
import app.embyr.core.model.OnboardingResultDto
import app.embyr.core.model.ExplorationPageDto
import app.embyr.core.model.RecommendationDecisionResult
import app.embyr.core.model.RecommendationResult
import app.embyr.core.model.WorldDeltaPageDto
import app.embyr.core.model.WorldSnapshotDto

/** Typed transport boundary shared by the Android foundation and M7-03 journey repositories. */
interface EmbyrApi {
    suspend fun bootstrap(): ApiResult<ProfileDto>
    suspend fun profile(): ApiResult<ProfileDto>
    suspend fun starterInterests(): ApiResult<StarterInterestPageDto>
    suspend fun completeOnboarding(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<OnboardingResultDto>
    suspend fun explorations(limit: Int, cursor: String? = null): ApiResult<ExplorationPageDto>
    suspend fun decideRecommendation(recommendationId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationDecisionResult>
    suspend fun world(): ApiResult<WorldSnapshotDto>
    suspend fun worldChanges(afterRevision: Long): ApiResult<WorldDeltaPageDto>
    suspend fun nextRecommendation(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationResult>
    suspend fun submitAnswer(sessionId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<AnswerAcknowledgmentDto>
}

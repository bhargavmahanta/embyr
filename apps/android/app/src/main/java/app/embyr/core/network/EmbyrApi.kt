package app.embyr.core.network

import app.embyr.core.model.AnswerAcknowledgmentDto
import app.embyr.core.model.ProfileDto
import app.embyr.core.model.RecommendationResult
import app.embyr.core.model.WorldDeltaPageDto
import app.embyr.core.model.WorldSnapshotDto

/** Typed transport boundary. Product repositories and UI are later-issue work. */
interface EmbyrApi {
    suspend fun bootstrap(): ApiResult<ProfileDto>
    suspend fun profile(): ApiResult<ProfileDto>
    suspend fun world(): ApiResult<WorldSnapshotDto>
    suspend fun worldChanges(afterRevision: Long): ApiResult<WorldDeltaPageDto>
    suspend fun nextRecommendation(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationResult>
    suspend fun submitAnswer(sessionId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<AnswerAcknowledgmentDto>
}

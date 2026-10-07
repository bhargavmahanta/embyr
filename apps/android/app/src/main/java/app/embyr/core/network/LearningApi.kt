package app.embyr.core.network

import app.embyr.core.model.*

/** Frozen M5 transport, alongside the existing M7-03 transport. */
interface LearningApi {
    suspend fun explorationList(limit: Int, cursor: String? = null): ApiResult<ExplorationListDto>
    suspend fun exploration(id: String): ApiResult<ExplorationDetailDto>
    suspend fun deliver(id: String, payload: ByteArray, key: String): ApiResult<DeliveryDto>
    suspend fun explorationAction(id: String, payload: ByteArray, key: String): ApiResult<ExplorationDto>
    suspend fun completeExploration(id: String, payload: ByteArray, key: String): ApiResult<ExplorationDto>
    suspend fun createReflection(id: String, payload: ByteArray, key: String): ApiResult<ReflectionDto>
    suspend fun editReflection(id: String, payload: ByteArray): ApiResult<ReflectionDto>
    suspend fun startAssessment(id: String, payload: ByteArray, key: String): ApiResult<AssessmentSessionDto>
    suspend fun assessmentSession(id: String): ApiResult<AssessmentSessionDto>
    suspend fun requestSupport(id: String, payload: ByteArray, key: String): ApiResult<SupportDto>
    suspend fun assessmentResponse(id: String): ApiResult<AssessmentResponseDto>
    suspend fun retryEvaluation(id: String, payload: ByteArray, key: String): ApiResult<EvaluationRetryDto>
}

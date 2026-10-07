package app.embyr.core.network

import app.embyr.auth.AuthGateway
import app.embyr.core.config.AppConfig
import app.embyr.core.model.*
import app.embyr.core.model.AnswerAcknowledgmentDto
import app.embyr.core.model.ProfileDto
import app.embyr.core.model.StarterInterestPageDto
import app.embyr.core.model.OnboardingResultDto
import app.embyr.core.model.ExplorationPageDto
import app.embyr.core.model.AcceptedExplorationDto
import app.embyr.core.model.SkippedRecommendationDto
import app.embyr.core.model.RecommendationDecisionResult
import app.embyr.core.model.RecommendationDto
import app.embyr.core.model.RecommendationResult
import app.embyr.core.model.WorldDeltaPageDto
import app.embyr.core.model.WorldResyncRequiredDto
import app.embyr.core.model.WorldSnapshotDto
import java.io.IOException
import java.net.SocketTimeoutException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PATCH
import retrofit2.http.Path
import retrofit2.http.Query
import okhttp3.ResponseBody

private interface RawService {
    @GET("api/v1/explorations/{id}") suspend fun exploration(@Path("id") id: String): Response<ResponseBody>
    @GET("api/v1/assessment-sessions/{id}") suspend fun assessmentSession(@Path("id") id: String): Response<ResponseBody>
    @GET("api/v1/assessment-responses/{id}") suspend fun assessmentResponse(@Path("id") id: String): Response<ResponseBody>
    @PATCH("api/v1/reflections/{id}") suspend fun editReflection(@Path("id") id: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/explorations/{id}/delivery") suspend fun deliver(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/explorations/{id}/actions") suspend fun explorationAction(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/explorations/{id}/completion") suspend fun completeExploration(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/explorations/{id}/reflections") suspend fun createReflection(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/explorations/{id}/assessment-sessions") suspend fun startAssessment(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/assessment-sessions/{id}/support-requests") suspend fun requestSupport(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/assessment-responses/{id}/evaluation-retries") suspend fun retryEvaluation(@Path("id") id: String, @Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>

    @POST("api/v1/session/bootstrap") suspend fun bootstrap(): Response<ResponseBody>
    @GET("api/v1/me") suspend fun profile(): Response<ResponseBody>
    @GET("api/v1/catalog/starter-interests") suspend fun starterInterests(): Response<ResponseBody>
    @POST("api/v1/me/onboarding/complete")
    suspend fun completeOnboarding(@Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @GET("api/v1/explorations")
    suspend fun explorations(@Query("limit") limit: Int, @Query("cursor") cursor: String?): Response<ResponseBody>
    @POST("api/v1/recommendations/{id}/decision")
    suspend fun decideRecommendation(
        @Path("id") recommendationId: String,
        @Header("Idempotency-Key") key: String,
        @Body body: RequestBody,
    ): Response<ResponseBody>
    @GET("api/v1/world") suspend fun world(): Response<ResponseBody>
    @GET("api/v1/world/changes") suspend fun worldChanges(@Query("after_revision") after: Long): Response<ResponseBody>
    @POST("api/v1/recommendations/next")
    suspend fun nextRecommendation(@Header("Idempotency-Key") key: String, @Body body: RequestBody): Response<ResponseBody>
    @POST("api/v1/assessment-sessions/{id}/responses")
    suspend fun submitAnswer(
        @Path("id") sessionId: String,
        @Header("Idempotency-Key") key: String,
        @Body body: RequestBody,
    ): Response<ResponseBody>
}

class RetrofitEmbyrApi(config: AppConfig, auth: AuthGateway, client: OkHttpClient? = null) : EmbyrApi, LearningApi {
    private val json = Json { ignoreUnknownKeys = true }
    private val mediaType = "application/json; charset=utf-8".toMediaType()
    private val httpClient = (client?.newBuilder() ?: OkHttpClient.Builder())
        .addInterceptor(Interceptor { chain ->
            val token = runBlocking { auth.accessToken() }
            val request = chain.request().newBuilder().apply {
                if (token != null) header("Authorization", "Bearer $token")
            }.build()
            chain.proceed(request)
        })
        .authenticator(Authenticator { _, response ->
            if (response.priorResponse != null || !replayableAfter401(response.request)) return@Authenticator null
            val previous = response.request.header("Authorization")
            val token = runBlocking {
                val current = auth.accessToken()
                if (current != null && "Bearer $current" != previous) current
                else if (auth.refreshSession(previous?.removePrefix("Bearer "))) auth.accessToken() else null
            } ?: return@Authenticator null
            response.request.newBuilder().header("Authorization", "Bearer $token").build()
        })
        .build()
    private val service = Retrofit.Builder()
        .baseUrl(config.embyrApiBaseUrl)
        .client(httpClient)
        .addConverterFactory(json.asConverterFactory(mediaType))
        .build()
        .create(RawService::class.java)

    override suspend fun bootstrap() = execute({ service.bootstrap() }) { json.decodeFromString(ProfileDto.serializer(), it) }
    override suspend fun profile() = execute({ service.profile() }) { json.decodeFromString(ProfileDto.serializer(), it) }
    override suspend fun starterInterests() = execute({ service.starterInterests() }) {
        json.decodeFromString(StarterInterestPageDto.serializer(), it)
    }
    override suspend fun completeOnboarding(canonicalPayload: ByteArray, idempotencyKey: String) =
        execute({ service.completeOnboarding(idempotencyKey, canonicalPayload.toRequestBody(mediaType)) }) {
            json.decodeFromString(OnboardingResultDto.serializer(), it)
        }
    override suspend fun explorations(limit: Int, cursor: String?) = execute({ service.explorations(limit, cursor) }) {
        json.decodeFromString(ExplorationPageDto.serializer(), it)
    }
    override suspend fun decideRecommendation(recommendationId: String, canonicalPayload: ByteArray, idempotencyKey: String) =
        execute({ service.decideRecommendation(recommendationId, idempotencyKey, canonicalPayload.toRequestBody(mediaType)) }) { raw ->
            if (json.parseToJsonElement(raw).jsonObject["decision"]?.jsonPrimitive?.content == "SKIP") {
                RecommendationDecisionResult.Skipped(json.decodeFromString(SkippedRecommendationDto.serializer(), raw))
            } else {
                RecommendationDecisionResult.Accepted(json.decodeFromString(AcceptedExplorationDto.serializer(), raw))
            }
        }
    override suspend fun world() = execute({ service.world() }) { json.decodeFromString(WorldSnapshotDto.serializer(), it) }
    override suspend fun worldChanges(afterRevision: Long) = execute({ service.worldChanges(afterRevision) }) {
        json.decodeFromString(WorldDeltaPageDto.serializer(), it)
    }
    override suspend fun nextRecommendation(canonicalPayload: ByteArray, idempotencyKey: String) =
        execute({ service.nextRecommendation(idempotencyKey, canonicalPayload.toRequestBody(mediaType)) }) { raw ->
            val objectValue = json.parseToJsonElement(raw).jsonObject
            if ("recommendation" in objectValue && objectValue.getValue("recommendation").jsonPrimitive.content == "null") {
                RecommendationResult.NoResult
            } else {
                RecommendationResult.Found(json.decodeFromString(RecommendationDto.serializer(), raw))
            }
        }

    override suspend fun submitAnswer(sessionId: String, canonicalPayload: ByteArray, idempotencyKey: String) =
        execute({ service.submitAnswer(sessionId, idempotencyKey, canonicalPayload.toRequestBody(mediaType)) }, expectedStatus = 202) {
            json.decodeFromString(AnswerAcknowledgmentDto.serializer(), it)
        }

    override suspend fun explorationList(limit: Int, cursor: String?) = execute({ service.explorations(limit, cursor) }, expectedStatus = 200) { json.decodeFromString(ExplorationListDto.serializer(), it) }
    override suspend fun exploration(id: String) = execute({ service.exploration(id) }, expectedStatus = 200) { json.decodeFromString(ExplorationDetailDto.serializer(), it) }
    override suspend fun deliver(id: String, payload: ByteArray, key: String) = execute({ service.deliver(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(DeliveryDto.serializer(), it) }
    override suspend fun explorationAction(id: String, payload: ByteArray, key: String) = execute({ service.explorationAction(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(ExplorationDto.serializer(), it) }
    override suspend fun completeExploration(id: String, payload: ByteArray, key: String) = execute({ service.completeExploration(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(ExplorationDto.serializer(), it) }
    override suspend fun createReflection(id: String, payload: ByteArray, key: String) = execute({ service.createReflection(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(ReflectionDto.serializer(), it) }
    override suspend fun editReflection(id: String, payload: ByteArray) = execute({ service.editReflection(id, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(ReflectionDto.serializer(), it) }
    override suspend fun startAssessment(id: String, payload: ByteArray, key: String) = execute({ service.startAssessment(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(AssessmentSessionDto.serializer(), it) }
    override suspend fun assessmentSession(id: String) = execute({ service.assessmentSession(id) }, expectedStatus = 200) { json.decodeFromString(AssessmentSessionDto.serializer(), it) }
    override suspend fun requestSupport(id: String, payload: ByteArray, key: String) = execute({ service.requestSupport(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 200) { json.decodeFromString(SupportDto.serializer(), it) }
    override suspend fun assessmentResponse(id: String) = execute({ service.assessmentResponse(id) }, expectedStatus = 200) { json.decodeFromString(AssessmentResponseDto.serializer(), it) }
    override suspend fun retryEvaluation(id: String, payload: ByteArray, key: String) = execute({ service.retryEvaluation(id, key, payload.toRequestBody(mediaType)) }, expectedStatus = 202) { json.decodeFromString(EvaluationRetryDto.serializer(), it) }

    private suspend fun <T> execute(call: suspend () -> Response<ResponseBody>, expectedStatus: Int? = null, decode: (String) -> T): ApiResult<T> {
        val response = try {
            call()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: SocketTimeoutException) {
            return ApiResult.Failure(TransportError.AmbiguousTimeout)
        } catch (_: IOException) {
            return ApiResult.Failure(TransportError.Network("IO"))
        }
        val status = response.code()
        val body = try {
            (if (response.isSuccessful) response.body() else response.errorBody())?.string().orEmpty()
        } catch (_: SocketTimeoutException) {
            return ApiResult.Failure(TransportError.AmbiguousTimeout)
        } catch (_: IOException) {
            return ApiResult.Failure(TransportError.Network("BODY_READ"))
        }
        if (response.isSuccessful) {
            if (expectedStatus != null && status != expectedStatus) return ApiResult.Failure(TransportError.UnexpectedHttp(status, response.headers()["X-Request-ID"]))
            return try {
                ApiResult.Success(decode(body), status)
            } catch (_: SerializationException) {
                ApiResult.Failure(TransportError.Decode(status))
            } catch (_: IllegalArgumentException) {
                ApiResult.Failure(TransportError.Decode(status))
            }
        }
        if (status == 401) {
            val authProblem = runCatching { json.decodeFromString(ProblemDetails.serializer(), body) }.getOrNull()
            return ApiResult.Failure(TransportError.Authentication(authProblem))
        }
        if (status == 409) {
            val resync = runCatching { json.decodeFromString(WorldResyncRequiredDto.serializer(), body) }.getOrNull()
            if (resync?.code == "WORLD_RESYNC_REQUIRED") return ApiResult.Failure(TransportError.WorldResync(resync))
        }
        if (status == 422) {
            val validation = runCatching { json.decodeFromString(FastApiValidationError.serializer(), body) }.getOrNull()
            if (validation != null) return ApiResult.Failure(TransportError.Validation(status, validation.detail))
        }
        val problem = runCatching { json.decodeFromString(ProblemDetails.serializer(), body) }.getOrNull()
        if (problem?.code != null || problem?.title != null) return ApiResult.Failure(TransportError.Problem(status, problem))
        return ApiResult.Failure(TransportError.UnexpectedHttp(status, response.headers()["X-Request-ID"]))
    }

    private fun replayableAfter401(request: Request): Boolean {
        if (request.method == "GET") return true
        val body = request.body ?: return false
        return request.header("Idempotency-Key") != null && !body.isOneShot() && !body.isDuplex()
    }
}

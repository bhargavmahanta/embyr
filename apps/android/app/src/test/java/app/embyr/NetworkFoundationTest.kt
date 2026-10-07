package app.embyr

import app.embyr.auth.AuthGateway
import app.embyr.auth.AuthState
import app.embyr.auth.SessionIdentity
import app.embyr.core.config.AppConfig
import app.embyr.core.network.ApiResult
import app.embyr.core.network.RetrofitEmbyrApi
import app.embyr.core.network.TransportError
import app.embyr.core.model.RecommendationResult
import app.embyr.core.model.RecommendationDecisionResult
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class NetworkFoundationTest {
    private lateinit var server: MockWebServer
    private lateinit var auth: FakeAuth
    private lateinit var config: AppConfig

    @Before fun start() {
        server = MockWebServer().apply { start() }
        auth = FakeAuth()
        config = object : AppConfig {
            override val embyrApiBaseUrl = server.url("/").toString()
            override val supabaseUrl = "https://example.invalid/"
            override val supabasePublishableKey = "publishable-test-only"
        }
    }

    @After fun stop() { server.shutdown() }

    @Test fun bearerIsAttachedAndOneCoordinatedRefreshReplaysGet() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(MockResponse().setBody(PROFILE))
        val result = RetrofitEmbyrApi(config, auth).profile()
        assertTrue(result is ApiResult.Success)
        assertEquals("Bearer old-token", server.takeRequest().getHeader("Authorization"))
        assertEquals("Bearer new-token", server.takeRequest().getHeader("Authorization"))
        assertEquals(1, auth.refreshes)
    }

    @Test fun nullableRecommendationAnd202AcknowledgmentStayTyped() = runBlocking {
        server.enqueue(MockResponse().setBody("{\"recommendation\":null}"))
        server.enqueue(MockResponse().setResponseCode(202).setBody(
            """{"response_id":"00000000-0000-0000-0000-000000000004","evaluation_status":"PENDING","session_status":"WAITING_FOR_EVALUATION","next_interaction":null}"""
        ))
        val api = RetrofitEmbyrApi(config, auth)
        val recommendation = api.nextRecommendation("{}".toByteArray(), "key-1")
        assertEquals(RecommendationResult.NoResult, (recommendation as ApiResult.Success).value)
        val request = server.takeRequest()
        assertEquals("key-1", request.getHeader("Idempotency-Key"))
        assertEquals("{}", request.body.readUtf8())
        val answer = api.submitAnswer("session", "{}".toByteArray(), "key-2")
        assertEquals(202, (answer as ApiResult.Success).httpStatus)
        assertEquals("PENDING", answer.value.evaluationStatus)
    }

    @Test fun recommendationWithNullPresentationCopyStillDecodes() = runBlocking {
        server.enqueue(MockResponse().setBody(
            """{"id":"00000000-0000-0000-0000-000000000001","target_type":"LEARNING_ENTITY","entity":{"id":"entity-1","title":"Example"},"practical_challenge":null,"mode":"DISCOVER","distance_band":"NEAR","hook":null,"reason":null,"presented_at":"2026-09-30T00:00:00Z"}"""
        ))
        val result = RetrofitEmbyrApi(config, auth).nextRecommendation("{}".toByteArray(), "key-null-copy")
        val recommendation = (result as ApiResult.Success).value as RecommendationResult.Found
        assertEquals(null, recommendation.recommendation.hook)
        assertEquals(null, recommendation.recommendation.reason)
    }

    @Test fun supportIs200AndVersionedPatchHasNoIdempotencyHeader() = runBlocking {
        val support = """{"id":"support","level":"SMALL_NUDGE","content":{"text":"Reviewed nudge"}}"""
        val reflection = """{"id":"reflection","exploration_id":"exploration","entity_id":"entity","text":"Updated draft","version":3,"created_at":"now","updated_at":"now"}"""
        server.enqueue(MockResponse().setBody(support))
        server.enqueue(MockResponse().setResponseCode(202).setBody(support))
        server.enqueue(MockResponse().setBody(reflection))
        val api = RetrofitEmbyrApi(config, auth)
        val payload = "{\"interaction_id\":\"interaction\",\"level\":\"SMALL_NUDGE\"}".toByteArray()
        val result = api.requestSupport("session", payload, "support-key") as ApiResult.Success
        assertEquals("Reviewed nudge", result.value.content.text)
        val request = server.takeRequest()
        assertEquals("/api/v1/assessment-sessions/session/support-requests", request.path)
        assertEquals(payload.decodeToString(), request.body.readUtf8())
        assertEquals("support-key", request.getHeader("Idempotency-Key"))
        assertTrue(api.requestSupport("session", payload, "support-key") is ApiResult.Failure)
        server.takeRequest()
        val edit = "{\"base_version\":2,\"text\":\"Updated draft\"}".toByteArray()
        assertEquals(3L, (api.editReflection("reflection", edit) as ApiResult.Success).value.version)
        val patch = server.takeRequest()
        assertEquals("PATCH", patch.method)
        assertEquals("/api/v1/reflections/reflection", patch.path)
        assertEquals(null, patch.getHeader("Idempotency-Key"))
        assertEquals(edit.decodeToString(), patch.body.readUtf8())
    }

    @Test fun originalAnswerAckAndCurrentResponseHaveDifferentProgress() = runBlocking {
        val ack = """{"response_id":"response","evaluation_status":"PENDING","session_status":"WAITING_FOR_EVALUATION","next_interaction":null}"""
        val current = """{"response_id":"response","assessment_session_id":"session","session_status":"COMPLETED","support_used":null,"evaluation_run_id":"run","evaluation_status":"SUCCEEDED","result":"UNDERSTOOD","confidence":0.8,"feedback":"Reviewed feedback","failure_category":null,"retry_allowed":false}"""
        server.enqueue(MockResponse().setResponseCode(202).setBody(ack))
        server.enqueue(MockResponse().setBody(current))
        val api = RetrofitEmbyrApi(config, auth)
        assertEquals("PENDING", (api.submitAnswer("session", "{}".toByteArray(), "key") as ApiResult.Success).value.evaluationStatus)
        server.takeRequest()
        val response = (api.assessmentResponse("response") as ApiResult.Success).value
        assertEquals("SUCCEEDED", response.evaluationStatus)
        assertEquals("run", response.evaluationRunId)
        assertEquals("GET", server.takeRequest().method)
    }

    @Test fun retryRequires202AndPreservesEmptyBodyAndKey() = runBlocking {
        val body = """{"response_id":"response","evaluation_status":"PENDING","session_status":"WAITING_FOR_EVALUATION","next_interaction":null,"evaluation_run_id":"new-run"}"""
        server.enqueue(MockResponse().setResponseCode(202).setBody(body))
        server.enqueue(MockResponse().setResponseCode(200).setBody(body))
        val api = RetrofitEmbyrApi(config, auth)
        assertEquals("new-run", (api.retryEvaluation("response", "{}".toByteArray(), "new-key") as ApiResult.Success).value.evaluationRunId)
        val request = server.takeRequest()
        assertEquals("/api/v1/assessment-responses/response/evaluation-retries", request.path)
        assertEquals("{}", request.body.readUtf8())
        assertEquals("new-key", request.getHeader("Idempotency-Key"))
        assertTrue(api.retryEvaluation("response", "{}".toByteArray(), "new-key") is ApiResult.Failure)
    }

    @Test fun answerRejectsSynchronousSuccessStatus() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"response_id":"response","evaluation_status":"PENDING","session_status":"WAITING_FOR_EVALUATION","next_interaction":null}"""
        ))
        val result = RetrofitEmbyrApi(config, auth).submitAnswer("session", "{}".toByteArray(), "answer-key")
        assertTrue("An immutable asynchronous answer requires HTTP202", result is ApiResult.Failure)
        assertEquals(200, ((result as ApiResult.Failure).error as TransportError.UnexpectedHttp).httpStatus)
    }

    @Test fun keyedMutationReplaysOneExactRequestAfter401() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(MockResponse().setBody("{\"recommendation\":null}"))
        val payload = "{\"stable\":true}".toByteArray()
        val result = RetrofitEmbyrApi(config, auth).nextRecommendation(payload, "stable-key")
        assertEquals(RecommendationResult.NoResult, (result as ApiResult.Success).value)
        val first = server.takeRequest()
        val replay = server.takeRequest()
        assertEquals(first.path, replay.path)
        assertEquals(first.body.readByteString(), replay.body.readByteString())
        assertEquals("stable-key", first.getHeader("Idempotency-Key"))
        assertEquals(first.getHeader("Idempotency-Key"), replay.getHeader("Idempotency-Key"))
        assertEquals(1, auth.refreshes)
    }

    @Test fun problemValidationWorldResyncAndMalformedResponseStayDistinct() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409).setBody(
            """{"type":"about:blank","title":"Conflict","status":409,"code":"OTHER_CODE","request_id":"00000000-0000-0000-0000-000000000001"}"""
        ))
        server.enqueue(MockResponse().setResponseCode(422).setBody(
            """{"detail":[{"loc":["body","mode"],"msg":"missing","type":"value_error"}]}"""
        ))
        server.enqueue(MockResponse().setResponseCode(409).setBody(
            """{"type":"about:blank","title":"World resync required","status":409,"code":"WORLD_RESYNC_REQUIRED","detail":"Fetch the World snapshot before requesting further changes.","request_id":"00000000-0000-0000-0000-000000000001","details":{"after_revision":9,"current_revision":2}}"""
        ))
        server.enqueue(MockResponse().setBody("{broken"))
        val api = RetrofitEmbyrApi(config, auth)
        val problem = (api.profile() as ApiResult.Failure).error as TransportError.Problem
        assertEquals("OTHER_CODE", problem.details.code)
        assertEquals("00000000-0000-0000-0000-000000000001", problem.details.requestId)
        assertTrue((api.profile() as ApiResult.Failure).error is TransportError.Validation)
        assertTrue((api.worldChanges(9) as ApiResult.Failure).error is TransportError.WorldResync)
        assertTrue((api.profile() as ApiResult.Failure).error is TransportError.Decode)
    }

    @Test fun timeoutIsAmbiguousAndUnkeyedPostIsNotReplayed() = runBlocking {
        server.enqueue(MockResponse().setBody(PROFILE).setBodyDelay(500, TimeUnit.MILLISECONDS))
        val timeoutClient = OkHttpClient.Builder().readTimeout(50, TimeUnit.MILLISECONDS).build()
        val timeout = RetrofitEmbyrApi(config, auth, timeoutClient).profile()
        assertTrue((timeout as ApiResult.Failure).error is TransportError.AmbiguousTimeout)
        server.takeRequest()
        server.enqueue(MockResponse().setResponseCode(401))
        val bootstrap = RetrofitEmbyrApi(config, auth).bootstrap()
        assertTrue((bootstrap as ApiResult.Failure).error is TransportError.Authentication)
        assertEquals("POST", server.takeRequest().method)
        assertEquals(0, auth.refreshes)
    }

    @Test fun journeyEndpointsStayTypedAndPreserveKeyedBodies() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":"00000000-0000-0000-0000-000000000001","entity_type":"AREA","entity_version":2,"title":"Space","summary":"Look up"}]}"""))
        server.enqueue(MockResponse().setBody("""{"preferences":{"adventure_preference":"BALANCED","preferred_effort":"15_20_MIN","support_style":"SMALL_HINT","practical_opt_in":false,"version":1},"onboarding_completed_at":"2026-10-01T00:00:00Z"}"""))
        server.enqueue(MockResponse().setBody("""{"items":[{"id":"00000000-0000-0000-0000-000000000002","recommendation_id":"00000000-0000-0000-0000-000000000003","status":"ACTIVE"}],"next_cursor":"next"}"""))
        server.enqueue(MockResponse().setBody("""{"recommendation_id":"00000000-0000-0000-0000-000000000003","decision":"SKIP"}"""))
        server.enqueue(MockResponse().setBody("""{"id":"00000000-0000-0000-0000-000000000002","entity":{"id":"00000000-0000-0000-0000-000000000004","title":"Space"},"entity_version":2,"practical_challenge_id":null,"learning_intent":"DIRECT_INTEREST","status":"ACTIVE","started_at":"2026-10-01T00:00:00Z","returned_at":null,"paused_at":null,"completed_at":null,"version":1}"""))
        val api = RetrofitEmbyrApi(config, auth)
        assertEquals("AREA", (api.starterInterests() as ApiResult.Success).value.items.single().entityType)
        assertEquals("/api/v1/catalog/starter-interests", server.takeRequest().path)
        val onboarding = api.completeOnboarding("{\"fixed\":true}".toByteArray(), "onboarding-key") as ApiResult.Success
        assertEquals("BALANCED", onboarding.value.preferences.adventurePreference)
        val onRequest = server.takeRequest()
        assertEquals("onboarding-key", onRequest.getHeader("Idempotency-Key"))
        assertEquals("{\"fixed\":true}", onRequest.body.readUtf8())
        val page = api.explorations(100, "previous") as ApiResult.Success
        assertEquals("next", page.value.nextCursor)
        assertEquals("/api/v1/explorations?limit=100&cursor=previous", server.takeRequest().path)
        val skipped = api.decideRecommendation("00000000-0000-0000-0000-000000000003", "{}".toByteArray(), "skip-key") as ApiResult.Success
        assertTrue(skipped.value is RecommendationDecisionResult.Skipped)
        assertEquals("skip-key", server.takeRequest().getHeader("Idempotency-Key"))
        val accepted = api.decideRecommendation("00000000-0000-0000-0000-000000000003", "{}".toByteArray(), "accept-key") as ApiResult.Success
        assertTrue(accepted.value is RecommendationDecisionResult.Accepted)
        assertEquals("accept-key", server.takeRequest().getHeader("Idempotency-Key"))
    }

    @Test fun unmappedIdentityRetainsProblemCodeAndRequestId() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(
            """{"type":"about:blank","title":"Unmapped identity","status":401,"code":"UNMAPPED_IDENTITY","request_id":"request-123"}"""
        ))
        val result = RetrofitEmbyrApi(config, auth).bootstrap() as ApiResult.Failure
        val error = result.error as TransportError.Authentication
        assertEquals("UNMAPPED_IDENTITY", error.details?.code)
        assertEquals("request-123", error.details?.requestId)
        assertEquals(0, auth.refreshes)
    }

    private class FakeAuth : AuthGateway {
        private val mutable = MutableStateFlow<AuthState>(AuthState.TokenAvailable(SessionIdentity("external")))
        override val state: StateFlow<AuthState> = mutable
        var token = "old-token"
        var refreshes = 0
        override suspend fun restoreSession() = state.value
        override suspend fun refreshSession(expectedAccessToken: String?): Boolean { refreshes++; token = "new-token"; return true }
        override suspend fun signOut() { mutable.value = AuthState.SignedOut }
        override suspend fun accessToken() = token
        override suspend fun requestEmailCode(email: String) = app.embyr.auth.EmailCodeResult.Sent
        override suspend fun verifyEmailCode(email: String, code: String) = app.embyr.auth.EmailCodeResult.Authenticated
    }

    companion object {
        private const val PROFILE = """{"id":"00000000-0000-0000-0000-000000000001","onboarding_completed_at":null,"preferences":null,"world_revision":0}"""
    }
}

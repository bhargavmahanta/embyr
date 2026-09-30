package app.embyr

import app.embyr.auth.AuthGateway
import app.embyr.auth.AuthState
import app.embyr.auth.SessionIdentity
import app.embyr.core.config.AppConfig
import app.embyr.core.network.ApiResult
import app.embyr.core.network.RetrofitEmbyrApi
import app.embyr.core.network.TransportError
import app.embyr.core.model.RecommendationResult
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

    private class FakeAuth : AuthGateway {
        private val mutable = MutableStateFlow<AuthState>(AuthState.TokenAvailable(SessionIdentity("external")))
        override val state: StateFlow<AuthState> = mutable
        var token = "old-token"
        var refreshes = 0
        override suspend fun restoreSession() = state.value
        override suspend fun refreshSession(expectedAccessToken: String?): Boolean { refreshes++; token = "new-token"; return true }
        override suspend fun signOut() { mutable.value = AuthState.SignedOut }
        override suspend fun accessToken() = token
    }

    companion object {
        private const val PROFILE = """{"id":"00000000-0000-0000-0000-000000000001","onboarding_completed_at":null,"preferences":null,"world_revision":0}"""
    }
}

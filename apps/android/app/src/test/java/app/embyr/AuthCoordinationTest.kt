package app.embyr

import app.embyr.auth.AuthSessionBackend
import app.embyr.auth.AuthState
import app.embyr.auth.EmailCodeResult
import app.embyr.auth.OwnerSession
import app.embyr.auth.SecureCodeVerifierCache
import app.embyr.auth.SecureSessionManager
import app.embyr.auth.SessionIdentity
import app.embyr.auth.SessionStore
import app.embyr.auth.SupabaseAuthGateway
import app.embyr.auth.configureFoundationAuth
import io.github.jan.supabase.annotations.SupabaseExperimental
import io.github.jan.supabase.auth.AuthConfig
import io.github.jan.supabase.auth.FlowType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthCoordinationTest {
    @OptIn(SupabaseExperimental::class)
    @Test fun sdkConfigurationDisablesEveryUnmanagedRefreshPath() {
        val config = AuthConfig().apply { configureFoundationAuth(MemoryStore(), MemoryStore()) }
        assertFalse(config.autoLoadFromStorage)
        assertTrue(config.autoSaveToStorage)
        assertFalse(config.alwaysAutoRefresh)
        assertFalse(config.enableLifecycleCallbacks)
        assertFalse(config.checkSessionOnRequest)
        assertEquals(FlowType.PKCE, config.flowType)
        assertTrue(config.sessionManager is SecureSessionManager)
        assertTrue(config.codeVerifierCache is SecureCodeVerifierCache)
    }

    @Test fun restoreLoadsWithoutAutoRefreshAndPublishesStoredSession() = runBlocking {
        val backend = FakeBackend()
        val gateway = gateway(backend)
        assertTrue(gateway.restoreSession() is AuthState.TokenAvailable)
        assertEquals(listOf(false), backend.loadAutoRefreshValues)
        assertEquals(0, backend.refreshes)
        assertEquals("old-token", gateway.accessToken())
    }

    @Test fun signOutWaitsForRefreshAndCannotResurrectSession() = runBlocking {
        val backend = FakeBackend()
        val sessionStore = MemoryStore("stored-session")
        val verifierStore = MemoryStore("stored-verifier")
        val owner = OwnerSession().apply { switchTo("owner-a") }
        val gateway = SupabaseAuthGateway(backend, sessionStore, verifierStore, owner)
        gateway.restoreSession()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        backend.pauseRefresh(started, release)

        val refresh = async(start = CoroutineStart.UNDISPATCHED) { gateway.refreshSession("old-token") }
        started.await()
        val signOut = async(start = CoroutineStart.UNDISPATCHED) { gateway.signOut() }
        yield()
        assertFalse(signOut.isCompleted)
        release.complete(Unit)
        assertTrue(refresh.await())
        signOut.await()
        yield()
        assertEquals(AuthState.SignedOut, gateway.state.value)
        assertFalse(backend.hasSession())
        assertNull(gateway.accessToken())
        assertNull(sessionStore.read())
        assertNull(verifierStore.read())
        assertNull(owner.owner.value)
        assertEquals(1, backend.refreshes)
    }

    @Test fun tokenReaderWaitsForRefreshAndReceivesNewToken() = runBlocking {
        val backend = FakeBackend()
        val gateway = gateway(backend)
        gateway.restoreSession()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        backend.pauseRefresh(started, release)

        val refresh = async(start = CoroutineStart.UNDISPATCHED) { gateway.refreshSession("old-token") }
        started.await()
        val reader = async(start = CoroutineStart.UNDISPATCHED) { gateway.accessToken() }
        yield()
        assertFalse(reader.isCompleted)
        release.complete(Unit)
        assertTrue(refresh.await())
        assertEquals("new-token", reader.await())
        assertTrue(gateway.refreshSession("old-token"))
        assertEquals(1, backend.refreshes)
    }

    @Test fun emailCodeRequestUsesClosedEnrollmentAndVerificationPublishesOnlyAuthenticatedSession() = runBlocking {
        val backend = FakeBackend()
        val gateway = gateway(backend)
        gateway.restoreSession()
        gateway.signOut()
        assertEquals(EmailCodeResult.Sent, gateway.requestEmailCode(" learner@example.com "))
        assertEquals("learner@example.com", backend.requestedEmail)
        backend.verifyAuthenticated = false
        assertTrue(gateway.verifyEmailCode("learner@example.com", "123456") is EmailCodeResult.Failed)
        assertEquals(AuthState.SignedOut, gateway.state.value)
        backend.verifyAuthenticated = true
        assertEquals(EmailCodeResult.Authenticated, gateway.verifyEmailCode("learner@example.com", "123456"))
        assertTrue(gateway.state.value is AuthState.TokenAvailable)
    }

    @Test fun verificationWaitsForRefreshUnderOneAuthMutex() = runBlocking {
        val backend = FakeBackend()
        val gateway = gateway(backend)
        gateway.restoreSession()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        backend.pauseRefresh(started, release)
        val refresh = async(start = CoroutineStart.UNDISPATCHED) { gateway.refreshSession("old-token") }
        started.await()
        val verify = async(start = CoroutineStart.UNDISPATCHED) { gateway.verifyEmailCode("learner@example.com", "123456") }
        yield()
        assertFalse(verify.isCompleted)
        release.complete(Unit)
        assertTrue(refresh.await())
        assertEquals(EmailCodeResult.Authenticated, verify.await())
        assertEquals("otp-token", gateway.accessToken())
    }

    private fun gateway(backend: FakeBackend) =
        SupabaseAuthGateway(backend, MemoryStore(), MemoryStore(), OwnerSession())

    private class MemoryStore(initial: String? = null) : SessionStore {
        private var value = initial?.toByteArray()
        override suspend fun read(): ByteArray? = value
        override suspend fun write(plaintext: ByteArray) { value = plaintext }
        override suspend fun delete() { value = null }
    }

    private class FakeBackend : AuthSessionBackend {
        val loadAutoRefreshValues = mutableListOf<Boolean>()
        var refreshes = 0
        var requestedEmail: String? = null
        var verifyAuthenticated = true
        private var token: String? = null
        private var refreshStarted: CompletableDeferred<Unit>? = null
        private var releaseRefresh: CompletableDeferred<Unit>? = null

        fun pauseRefresh(started: CompletableDeferred<Unit>, release: CompletableDeferred<Unit>) {
            refreshStarted = started
            releaseRefresh = release
        }

        override suspend fun loadFromStorage(autoRefresh: Boolean): Boolean {
            loadAutoRefreshValues += autoRefresh
            token = "old-token"
            return true
        }

        override fun hasSession(): Boolean = token != null
        override fun accessTokenOrNull(): String? = token
        override suspend fun sessionIdentityOrNull(): SessionIdentity? =
            if (token == null) null else SessionIdentity("external-user")

        override suspend fun refreshCurrentSession() {
            refreshes++
            refreshStarted?.complete(Unit)
            releaseRefresh?.await()
            token = "new-token"
        }

        override suspend fun clearSession() { token = null }
        override suspend fun requestEmailCode(email: String) { requestedEmail = email }
        override suspend fun verifyEmailCode(email: String, code: String): Boolean {
            if (verifyAuthenticated) token = "otp-token"
            return verifyAuthenticated
        }
    }
}

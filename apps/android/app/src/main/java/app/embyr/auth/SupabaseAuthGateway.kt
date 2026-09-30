package app.embyr.auth

import app.embyr.core.config.AppConfig
import io.github.jan.supabase.annotations.SupabaseExperimental
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.auth.AuthConfig
import io.github.jan.supabase.auth.FlowType
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.exceptions.RestException
import io.github.jan.supabase.logging.LogLevel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

@OptIn(SupabaseExperimental::class)
internal fun AuthConfig.configureFoundationAuth(sessionStore: SessionStore, codeVerifierStore: SessionStore) {
    sessionManager = SecureSessionManager(sessionStore)
    codeVerifierCache = SecureCodeVerifierCache(codeVerifierStore)
    flowType = FlowType.PKCE
    autoLoadFromStorage = false
    autoSaveToStorage = true
    alwaysAutoRefresh = false
    enableLifecycleCallbacks = false
    checkSessionOnRequest = false
}

/** Keeps SDK calls behind the same gateway lock and permits deterministic coordination tests. */
internal interface AuthSessionBackend {
    suspend fun loadFromStorage(autoRefresh: Boolean): Boolean
    fun hasSession(): Boolean
    fun accessTokenOrNull(): String?
    suspend fun sessionIdentityOrNull(): SessionIdentity?
    suspend fun refreshCurrentSession()
    suspend fun clearSession()
}

private class SupabaseAuthBackend(
    config: AppConfig,
    sessionStore: SessionStore,
    codeVerifierStore: SessionStore,
) : AuthSessionBackend {
    private val client = createSupabaseClient(config.supabaseUrl, config.supabasePublishableKey) {
        defaultLogLevel = LogLevel.NONE
        install(Auth) { configureFoundationAuth(sessionStore, codeVerifierStore) }
    }

    override suspend fun loadFromStorage(autoRefresh: Boolean): Boolean = client.auth.loadFromStorage(autoRefresh)
    override fun hasSession(): Boolean = client.auth.currentSessionOrNull() != null
    override fun accessTokenOrNull(): String? = client.auth.currentAccessTokenOrNull()

    override suspend fun sessionIdentityOrNull(): SessionIdentity? {
        val status = client.auth.sessionStatus.value
        if (status !is SessionStatus.Authenticated) return null
        val externalId = status.session.user?.id ?: try {
            client.auth.retrieveUserForCurrentSession(updateSession = true).id
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return null
        }
        return SessionIdentity(externalId)
    }

    override suspend fun refreshCurrentSession() { client.auth.refreshCurrentSession() }
    override suspend fun clearSession() { client.auth.clearSession() }
}

class SupabaseAuthGateway internal constructor(
    private val backend: AuthSessionBackend,
    private val sessionStore: SessionStore,
    private val codeVerifierStore: SessionStore,
    private val ownerSession: OwnerSession,
) : AuthGateway {
    constructor(
        config: AppConfig,
        sessionStore: SessionStore,
        codeVerifierStore: SessionStore,
        ownerSession: OwnerSession,
    ) : this(SupabaseAuthBackend(config, sessionStore, codeVerifierStore), sessionStore, codeVerifierStore, ownerSession)

    private val authMutex = Mutex()
    private val mutableState = MutableStateFlow<AuthState>(AuthState.Restoring)
    override val state: StateFlow<AuthState> = mutableState

    override suspend fun restoreSession(): AuthState = authMutex.withLock {
        mutableState.value = AuthState.Restoring
        val loaded = try {
            backend.loadFromStorage(autoRefresh = false)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            false
        }
        val restored = if (loaded) stateFromSdkLocked() else AuthState.SignedOut
        if (restored == AuthState.SignedOut) clearLocalSessionLocked()
        mutableState.value = restored
        restored
    }

    override suspend fun refreshSession(expectedAccessToken: String?): Boolean = authMutex.withLock {
        if (!backend.hasSession()) return@withLock false
        val currentToken = currentAccessTokenLocked()
        if (expectedAccessToken != null && currentToken != null && currentToken != expectedAccessToken) {
            return@withLock state.value is AuthState.TokenAvailable
        }
        val previous = state.value
        mutableState.value = AuthState.Refreshing
        var refreshed = false
        val next = try {
            backend.refreshCurrentSession()
            refreshed = true
            stateFromSdkLocked()
        } catch (cancelled: CancellationException) {
            mutableState.value = previous
            throw cancelled
        } catch (error: RestException) {
            if (error.statusCode in 400..499) AuthState.SignedOut else previous
        } catch (_: Exception) {
            previous
        }
        if (next == AuthState.SignedOut) clearLocalSessionLocked()
        mutableState.value = next
        refreshed && next is AuthState.TokenAvailable
    }

    override suspend fun signOut() = authMutex.withLock {
        try {
            clearLocalSessionLocked()
        } finally {
            mutableState.value = AuthState.SignedOut
        }
    }

    override suspend fun accessToken(): String? = authMutex.withLock {
        if (state.value is AuthState.TokenAvailable) currentAccessTokenLocked() else null
    }

    private fun currentAccessTokenLocked(): String? = backend.accessTokenOrNull()

    private suspend fun stateFromSdkLocked(): AuthState {
        if (currentAccessTokenLocked() == null) return AuthState.SignedOut
        return backend.sessionIdentityOrNull()?.let(AuthState::TokenAvailable) ?: AuthState.SignedOut
    }

    private suspend fun clearLocalSessionLocked() {
        ownerSession.switchTo(null)
        try {
            backend.clearSession()
        } finally {
            try {
                sessionStore.delete()
            } finally {
                codeVerifierStore.delete()
            }
        }
    }
}

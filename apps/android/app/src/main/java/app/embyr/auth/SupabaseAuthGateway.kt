package app.embyr.auth

import app.embyr.core.config.AppConfig
import io.github.jan.supabase.auth.Auth
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

class SupabaseAuthGateway(
    config: AppConfig,
    sessionStore: SessionStore,
    codeVerifierStore: SessionStore,
    private val ownerSession: OwnerSession,
) : AuthGateway {
    private val client = createSupabaseClient(config.supabaseUrl, config.supabasePublishableKey) {
        defaultLogLevel = LogLevel.NONE
        install(Auth) {
            sessionManager = SecureSessionManager(sessionStore)
            codeVerifierCache = SecureCodeVerifierCache(codeVerifierStore)
            flowType = FlowType.PKCE
            autoLoadFromStorage = false
            autoSaveToStorage = true
        }
    }
    private val refreshMutex = Mutex()
    private val mutableState = MutableStateFlow<AuthState>(AuthState.Restoring)
    override val state: StateFlow<AuthState> = mutableState
    private val store = sessionStore

    override suspend fun restoreSession(): AuthState {
        mutableState.value = AuthState.Restoring
        val loaded = try {
            client.auth.loadFromStorage()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            false
        }
        val restored = if (loaded) stateFromSdk() else AuthState.SignedOut
        if (restored == AuthState.SignedOut) clearLocalSession()
        mutableState.value = restored
        return mutableState.value
    }

    override suspend fun refreshSession(expectedAccessToken: String?): Boolean = refreshMutex.withLock {
        if (client.auth.currentSessionOrNull() == null) return@withLock false
        if (expectedAccessToken != null && client.auth.currentAccessTokenOrNull() != expectedAccessToken) {
            return@withLock true
        }
        val previous = state.value
        mutableState.value = AuthState.Refreshing
        var refreshed = false
        val next = try {
            client.auth.refreshCurrentSession()
            refreshed = true
            stateFromSdk()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: RestException) {
            if (error.statusCode in 400..499) AuthState.SignedOut else previous
        } catch (_: Exception) {
            previous
        }
        if (next == AuthState.SignedOut) clearLocalSession()
        mutableState.value = next
        refreshed && next is AuthState.TokenAvailable
    }

    override suspend fun signOut() {
        mutableState.value = AuthState.SignedOut
        clearLocalSession()
    }

    override suspend fun accessToken(): String? =
        if (state.value is AuthState.TokenAvailable) client.auth.currentAccessTokenOrNull() else null

    private suspend fun stateFromSdk(): AuthState {
        val status = client.auth.sessionStatus.value
        if (status !is SessionStatus.Authenticated) return AuthState.SignedOut
        val externalId = status.session.user?.id ?: try {
            client.auth.retrieveUserForCurrentSession(updateSession = true).id
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return AuthState.SignedOut
        }
        return AuthState.TokenAvailable(SessionIdentity(externalId))
    }

    private suspend fun clearLocalSession() {
        ownerSession.switchTo(null)
        try {
            client.auth.clearSession()
        } finally {
            store.delete()
        }
    }
}

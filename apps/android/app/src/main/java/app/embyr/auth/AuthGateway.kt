package app.embyr.auth

import kotlinx.coroutines.flow.StateFlow

data class SessionIdentity(val externalUserId: String)

sealed interface AuthState {
    data object Restoring : AuthState
    data object SignedOut : AuthState
    data class TokenAvailable(val identity: SessionIdentity) : AuthState
    data object Refreshing : AuthState
}

interface AuthGateway {
    val state: StateFlow<AuthState>
    suspend fun restoreSession(): AuthState
    suspend fun refreshSession(expectedAccessToken: String? = null): Boolean
    suspend fun signOut()
    suspend fun accessToken(): String?
}

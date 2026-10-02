package app.embyr.feature.journey

import app.embyr.auth.AuthGateway
import app.embyr.auth.AuthState
import app.embyr.auth.OwnerSession
import app.embyr.core.model.ProfileDto
import app.embyr.core.network.ApiResult
import app.embyr.core.network.EmbyrApi
import app.embyr.core.network.TransportError
import java.util.UUID

sealed interface SessionOutcome {
    data object SignedOut : SessionOutcome
    data class Ready(val profile: ProfileDto) : SessionOutcome
    data class Recoverable(val error: TransportError?) : SessionOutcome
}

class SessionRepository(
    private val auth: AuthGateway,
    private val api: EmbyrApi,
    private val owners: OwnerSession,
) {
    suspend fun restore(): SessionOutcome = when (auth.restoreSession()) {
        is AuthState.TokenAvailable -> bootstrap()
        else -> SessionOutcome.SignedOut
    }

    suspend fun bootstrap(): SessionOutcome {
        if (auth.state.value !is AuthState.TokenAvailable) return SessionOutcome.SignedOut
        var result = api.bootstrap()
        if (result is ApiResult.Failure && (result.error is TransportError.Network || result.error is TransportError.AmbiguousTimeout)) {
            result = api.bootstrap() // Bounded retry only for this convergent bootstrap route.
        }
        if (result is ApiResult.Failure && result.error is TransportError.Authentication && result.error.details?.code != "UNMAPPED_IDENTITY") {
            val previousToken = auth.accessToken()
            if (!auth.refreshSession(previousToken)) {
                return if (auth.state.value == AuthState.SignedOut) SessionOutcome.SignedOut else SessionOutcome.Recoverable(result.error)
            }
            result = api.bootstrap() // Explicit one-time retry; OkHttp never replays this unkeyed POST.
        }
        if (result is ApiResult.Failure) {
            if (result.error is TransportError.Authentication && result.error.details?.code != "UNMAPPED_IDENTITY") {
                auth.signOut()
                return SessionOutcome.SignedOut
            }
            return SessionOutcome.Recoverable(result.error)
        }
        val profile = (result as ApiResult.Success).value
        if (runCatching { UUID.fromString(profile.id) }.isFailure) return SessionOutcome.Recoverable(null)
        owners.switchTo(profile.id)
        return when (val fresh = api.profile()) {
            is ApiResult.Success -> if (fresh.value.id == profile.id) SessionOutcome.Ready(fresh.value) else {
                owners.switchTo(null)
                SessionOutcome.Recoverable(null)
            }
            is ApiResult.Failure -> if (fresh.error is TransportError.Authentication) {
                auth.signOut()
                SessionOutcome.SignedOut
            } else SessionOutcome.Recoverable(fresh.error)
        }
    }

    suspend fun profile(): ApiResult<ProfileDto> = api.profile()
}

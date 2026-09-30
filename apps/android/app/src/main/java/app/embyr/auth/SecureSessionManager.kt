package app.embyr.auth

import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.exception.NoSessionFoundException
import io.github.jan.supabase.auth.user.UserSession
import kotlinx.serialization.json.Json

class SecureSessionManager(private val store: SessionStore) : SessionManager {
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun saveSession(session: UserSession) {
        store.write(json.encodeToString(UserSession.serializer(), session).toByteArray(Charsets.UTF_8))
    }

    override suspend fun loadSession(): UserSession {
        val raw = store.read() ?: throw NoSessionFoundException()
        return try {
            json.decodeFromString(UserSession.serializer(), raw.toString(Charsets.UTF_8))
        } catch (_: Exception) {
            store.delete()
            throw NoSessionFoundException()
        }
    }

    override suspend fun deleteSession() = store.delete()
}

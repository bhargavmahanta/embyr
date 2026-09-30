package app.embyr.auth

import io.github.jan.supabase.auth.CodeVerifierCache

/** PKCE state has its own Keystore key and ciphertext, separate from the auth session. */
class SecureCodeVerifierCache(private val store: SessionStore) : CodeVerifierCache {
    override suspend fun saveCodeVerifier(codeVerifier: String) {
        store.write(codeVerifier.toByteArray(Charsets.UTF_8))
    }

    override suspend fun loadCodeVerifier(): String? = store.read()?.toString(Charsets.UTF_8)

    override suspend fun deleteCodeVerifier() = store.delete()
}

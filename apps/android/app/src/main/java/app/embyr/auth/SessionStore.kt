package app.embyr.auth

interface SessionStore {
    suspend fun read(): ByteArray?
    suspend fun write(plaintext: ByteArray)
    suspend fun delete()
}

package app.embyr.auth

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

enum class AuthSecretKind(val fileName: String, val keyAlias: String) {
    SESSION("auth-session.bin", "embyr-auth-session-v1"),
    CODE_VERIFIER("auth-code-verifier.bin", "embyr_pkce_v1"),
}

class KeystoreSessionStore(context: Context, kind: AuthSecretKind = AuthSecretKind.SESSION) : SessionStore {
    private val file = AtomicFile(File(context.noBackupFilesDir, kind.fileName))
    private val mutex = Mutex()
    private val alias = kind.keyAlias

    override suspend fun read(): ByteArray? = withContext(Dispatchers.IO) {
        mutex.withLock {
            if (!file.baseFile.exists()) return@withLock null
            try {
                val envelope = file.openRead().use { it.readBytes() }
                require(envelope.size > 14 && envelope[0] == 1.toByte())
                val ivSize = envelope[1].toInt() and 0xff
                require(ivSize == 12 && envelope.size > ivSize + 18)
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, envelope.copyOfRange(2, 2 + ivSize)))
                cipher.doFinal(envelope.copyOfRange(2 + ivSize, envelope.size))
            } catch (_: Exception) {
                // An invalidated key or damaged envelope cannot be restored safely.
                file.delete()
                null
            }
        }
    }

    override suspend fun write(plaintext: ByteArray) = withContext(Dispatchers.IO) {
        mutex.withLock {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val iv = cipher.iv
            require(iv.size == 12)
            val envelope = byteArrayOf(1, iv.size.toByte()) + iv + cipher.doFinal(plaintext)
            val stream = file.startWrite()
            try {
                stream.write(envelope)
                file.finishWrite(stream)
            } catch (error: Exception) {
                file.failWrite(stream)
                throw error
            }
        }
    }

    override suspend fun delete() = withContext(Dispatchers.IO) { mutex.withLock { file.delete() } }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
        }.generateKey()
    }
}

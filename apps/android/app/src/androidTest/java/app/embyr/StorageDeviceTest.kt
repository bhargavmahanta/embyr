package app.embyr

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.embyr.auth.KeystoreSessionStore
import app.embyr.auth.AuthSecretKind
import app.embyr.auth.OwnerSession
import app.embyr.auth.SecureCodeVerifierCache
import app.embyr.core.model.WorldRegionDto
import app.embyr.core.model.WorldSnapshotDto
import app.embyr.core.storage.CommandEntity
import app.embyr.core.storage.CommandState
import app.embyr.core.storage.EmbyrDatabase
import app.embyr.core.storage.RoomCommandOutbox
import app.embyr.core.storage.RoomWorldStore
import java.io.File
import java.security.KeyStore
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StorageDeviceTest {
    private val databaseName = "foundation-test.db"
    private lateinit var context: Context
    private lateinit var database: EmbyrDatabase
    private lateinit var owners: OwnerSession

    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        context.deleteDatabase(databaseName)
        database = openDatabase()
        owners = OwnerSession().apply { switchTo("owner-a") }
    }

    @After fun teardown() {
        database.close()
        context.deleteDatabase(databaseName)
    }

    @Test fun outboxSurvivesRecreationWithSameBytesAndOwnerIsolation() = runBlocking {
        val payload = "{\"exact\":true}".toByteArray()
        RoomCommandOutbox(database.commandDao(), owners).enqueue(
            CommandEntity("command-a", "owner-a", "POST", "api/v1/test", payload, "key-a", 1000, CommandState.PENDING.name),
        )
        database.close()
        database = openDatabase()
        val reopened = RoomCommandOutbox(database.commandDao(), owners)
        val recovered = requireNotNull(reopened.get("owner-a", "command-a"))
        assertArrayEquals(payload, recovered.canonicalPayload)
        assertEquals("key-a", recovered.idempotencyKey)
        assertEquals(listOf("command-a"), reopened.unresolved("owner-a").map { it.id })
        try {
            reopened.get("owner-b", "command-a")
            fail("Cross-owner query was permitted")
        } catch (_: IllegalStateException) { }
        owners.switchTo("owner-b")
        assertTrue(reopened.unresolved("owner-b").isEmpty())
    }

    @Test fun worldRevisionAndObjectsRollBackTogetherAndNeverCrossOwners() = runBlocking {
        val store = RoomWorldStore(database, owners)
        val original = snapshot(1, listOf(region("region-1")))
        store.replaceSnapshot("owner-a", original, 1000)
        try {
            store.replaceSnapshot("owner-a", snapshot(0, emptyList()), 1500)
            fail("Older World revision should be rejected")
        } catch (_: IllegalArgumentException) { }
        try {
            store.getWorld("owner-b")
            fail("Cross-owner World query was permitted")
        } catch (_: IllegalStateException) { }
        val invalid = snapshot(2, listOf(region("region-2"), region("region-2")))
        try {
            store.replaceSnapshot("owner-a", invalid, 2000)
            fail("Duplicate region should have aborted the transaction")
        } catch (_: android.database.sqlite.SQLiteConstraintException) {
            // The second insert fails after deletion began; Room must roll everything back.
        }
        database.close()
        database = openDatabase()
        val recovered = requireNotNull(RoomWorldStore(database, owners).getWorld("owner-a"))
        assertEquals(1L, recovered.revision)
        assertEquals(listOf("region-1"), recovered.regions.map { it.id })
        owners.switchTo("owner-b")
        assertNull(RoomWorldStore(database, owners).getWorld("owner-b"))
    }

    @Test fun keystoreCiphertextSurvivesStoreRecreationAndCorruptionClears() = runBlocking {
        val file = File(context.noBackupFilesDir, "auth-session.bin")
        val store = KeystoreSessionStore(context)
        store.delete()
        val plaintext = "private-refresh-token".toByteArray()
        store.write(plaintext)
        assertFalse(file.readBytes().toString(Charsets.ISO_8859_1).contains("private-refresh-token"))
        assertArrayEquals(plaintext, KeystoreSessionStore(context).read())
        file.writeBytes(byteArrayOf(1, 12, 3))
        assertNull(KeystoreSessionStore(context).read())
        assertFalse(file.exists())
        store.write(plaintext)
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry("embyr-auth-session-v1")
        assertNull(KeystoreSessionStore(context).read())
        assertFalse(file.exists())
    }

    @Test fun codeVerifierUsesSeparateEncryptedStoreAndSurvivesRecreation() = runBlocking {
        val encrypted = File(context.noBackupFilesDir, AuthSecretKind.CODE_VERIFIER.fileName)
        val cache = SecureCodeVerifierCache(KeystoreSessionStore(context, AuthSecretKind.CODE_VERIFIER))
        cache.deleteCodeVerifier()
        cache.saveCodeVerifier("private-pkce-verifier")
        assertFalse(encrypted.readBytes().toString(Charsets.ISO_8859_1).contains("private-pkce-verifier"))
        val reopened = SecureCodeVerifierCache(KeystoreSessionStore(context, AuthSecretKind.CODE_VERIFIER))
        assertEquals("private-pkce-verifier", reopened.loadCodeVerifier())
        reopened.deleteCodeVerifier()
        assertFalse(encrypted.exists())
    }

    private fun openDatabase() = Room.databaseBuilder(context, EmbyrDatabase::class.java, databaseName).build()

    private fun region(id: String) = WorldRegionDto(id, "discovery", null, 0, 0, 1, 1, "grove")

    private fun snapshot(revision: Long, regions: List<WorldRegionDto>) = WorldSnapshotDto(
        revision = revision,
        layoutVersion = 1,
        generationSeed = "a".repeat(64),
        regions = regions,
        nodes = emptyList(),
        connections = emptyList(),
        artifacts = emptyList(),
    )
}

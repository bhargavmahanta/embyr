package app.embyr

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.embyr.core.storage.EmbyrDatabase
import app.embyr.core.storage.MIGRATION_1_2
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class JourneyMigrationDeviceTest {
    @get:Rule val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), EmbyrDatabase::class.java)

    @Test fun versionOneOutboxSurvivesAdditiveJourneyMigration() {
        val dbName = "journey-migration-test.db"
        helper.createDatabase(dbName, 1).apply {
            execSQL("""INSERT INTO commands (id, ownerId, method, relativeRoute, canonicalPayload, idempotencyKey, createdAtEpochMs, state, attempts) VALUES ('command-1', 'owner-a', 'POST', 'api/v1/test', X'7B7D', 'key-1', 1000, 'AMBIGUOUS', 1)""")
            close()
        }
        helper.runMigrationsAndValidate(dbName, 2, true, MIGRATION_1_2).apply {
            query("SELECT ownerId, idempotencyKey, state FROM commands WHERE id = 'command-1'").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("owner-a", cursor.getString(0))
                assertEquals("key-1", cursor.getString(1))
                assertEquals("AMBIGUOUS", cursor.getString(2))
            }
            query("SELECT COUNT(*) FROM journey_state").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(0, cursor.getInt(0))
            }
            close()
        }
    }
}

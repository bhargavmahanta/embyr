package app.embyr

import androidx.room.testing.MigrationTestHelper
import androidx.test.platform.app.InstrumentationRegistry
import app.embyr.core.storage.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class LearningMigrationDeviceTest {
    @get:Rule val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), EmbyrDatabase::class.java)
    @Test fun versionOnePreservesBothOwnersCommandsAndWorldThroughThree() = migrate(1)
    @Test fun versionTwoPreservesJourneyAndCommandsThroughThree() = migrate(2)
    private fun migrate(start: Int) {
        val name = "m704-migration-$start.db"
        helper.createDatabase(name,start).apply {
            listOf("a","b").forEach { owner ->
                execSQL("INSERT INTO commands (id,ownerId,method,relativeRoute,canonicalPayload,idempotencyKey,createdAtEpochMs,state,attempts) VALUES (?,?,'POST','api/v1/test',X'7B226B223A317D',?,1000,'AMBIGUOUS',2)", arrayOf("command-$owner",owner,"key-$owner"))
                execSQL("INSERT INTO world_meta (ownerId,revision,layoutVersion,generationSeed,committedAtEpochMs) VALUES (?,7,1,'seed',1000)", arrayOf(owner))
                if (start == 2) execSQL("INSERT INTO journey_state (ownerId,draftStarterIdsJson,noResult,acceptedExplorationId) VALUES (?,'[]',0,'exploration')", arrayOf(owner))
            }; close()
        }
        helper.runMigrationsAndValidate(name,3,true,MIGRATION_1_2,MIGRATION_2_3).apply {
            query("SELECT ownerId,idempotencyKey,hex(canonicalPayload),state FROM commands ORDER BY ownerId").use { cursor ->
                listOf("a","b").forEach { owner -> assertTrue(cursor.moveToNext()); assertEquals(owner,cursor.getString(0)); assertEquals("key-$owner",cursor.getString(1)); assertEquals("7B226B223A317D",cursor.getString(2)); assertEquals("AMBIGUOUS",cursor.getString(3)) }
                assertFalse(cursor.moveToNext())
            }
            query("SELECT COUNT(*),MIN(revision) FROM world_meta").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)); assertEquals(7,it.getInt(1)) }
            if (start == 2) query("SELECT COUNT(*) FROM journey_state WHERE acceptedExplorationId = 'exploration'").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)) }
            listOf("exploration_state","assessment_state","activity_state","learning_receipts").forEach { table ->
                query("SELECT COUNT(*) FROM $table").use { assertTrue(it.moveToFirst()); assertEquals(0,it.getInt(0)) }
            }
            close()
        }
    }
}

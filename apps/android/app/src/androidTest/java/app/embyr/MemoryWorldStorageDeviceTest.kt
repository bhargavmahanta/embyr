package app.embyr

import android.content.Context
import androidx.room.Room
import androidx.room.testing.MigrationTestHelper
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import app.embyr.auth.*
import app.embyr.core.model.*
import app.embyr.core.storage.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class MemoryWorldStorageDeviceTest {
    @get:Rule val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), EmbyrDatabase::class.java)
    @Test fun versionOneToFourRetainsBothOwners() = migrate(1)
    @Test fun versionTwoToFourRetainsBothOwners() = migrate(2)
    @Test fun versionThreeToFourRetainsBothOwnersAndDrafts() = migrate(3)
    private fun migrate(start: Int) {
        val name = "m705-migration-$start.db"
        helper.createDatabase(name,start).apply {
            listOf("a","b").forEach { owner ->
                execSQL("INSERT INTO commands (id,ownerId,method,relativeRoute,canonicalPayload,idempotencyKey,createdAtEpochMs,state,attempts) VALUES (?,?,'POST','api/v1/test',X'7B226B223A317D',?,1000,'AMBIGUOUS',2)",arrayOf("command-$owner",owner,"key-$owner"))
                execSQL("INSERT INTO world_meta (ownerId,revision,layoutVersion,generationSeed,committedAtEpochMs) VALUES (?,7,1,'seed',1000)",arrayOf(owner))
                execSQL("INSERT INTO world_nodes (ownerId,objectId,payloadJson) VALUES (?,'node','retained')",arrayOf(owner))
                if(start >= 2) execSQL("INSERT INTO journey_state (ownerId,draftStarterIdsJson,noResult,acceptedExplorationId) VALUES (?,'[]',0,'exploration')",arrayOf(owner))
                if(start >= 3) {
                    execSQL("INSERT INTO exploration_state (ownerId,explorationId,draft,draftInitialized,lifecycleNeedsRefresh) VALUES (?,'exploration','draft',1,1)",arrayOf(owner))
                    execSQL("INSERT INTO learning_receipts (ownerId,commandId,resultJson) VALUES (?,'cmd','receipt')",arrayOf(owner))
                    execSQL("INSERT INTO assessment_state (ownerId,sessionId,explorationId,sessionJson,responseId,knownRunId,selectedOptionId) VALUES (?,'session','exploration','session-json','response','run','option')",arrayOf(owner))
                }
            }; close()
        }
        helper.runMigrationsAndValidate(name,4,true,MIGRATION_1_2,MIGRATION_2_3,MIGRATION_3_4).apply {
            query("SELECT ownerId,idempotencyKey,hex(canonicalPayload),state FROM commands ORDER BY ownerId").use { cursor ->
                listOf("a","b").forEach { owner -> assertTrue(cursor.moveToNext()); assertEquals(owner,cursor.getString(0)); assertEquals("key-$owner",cursor.getString(1)); assertEquals("7B226B223A317D",cursor.getString(2)); assertEquals("AMBIGUOUS",cursor.getString(3)) }
                assertFalse(cursor.moveToNext())
            }
            query("SELECT COUNT(*),MIN(revision),MAX(cacheGeneration) FROM world_meta").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)); assertEquals(7,it.getInt(1)); assertEquals(0,it.getInt(2)) }
            query("SELECT COUNT(*) FROM world_nodes WHERE payloadJson = 'retained'").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)) }
            if(start >= 3) {
                query("SELECT COUNT(*) FROM exploration_state WHERE draft = 'draft' AND draftInitialized = 1 AND lifecycleNeedsRefresh = 1").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)) }
                query("SELECT COUNT(*) FROM assessment_state WHERE selectedOptionId = 'option' AND knownRunId = 'run'").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)) }
                query("SELECT COUNT(*) FROM learning_receipts WHERE resultJson = 'receipt'").use { assertTrue(it.moveToFirst()); assertEquals(2,it.getInt(0)) }
            }
            query("SELECT COUNT(*) FROM memory_cache").use { assertTrue(it.moveToFirst()); assertEquals(0,it.getInt(0)) }
            close()
        }
    }
    @Test fun exactPutSurvivesReopenAndGenerationRejectsStaleOwner() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>(); val name = "m705-put.db"
        context.deleteDatabase(name)
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        var db = Room.databaseBuilder(context,EmbyrDatabase::class.java,name).build()
        val bytes = "{\"base_version\":7,\"preference\":\"LESS\"}".toByteArray()
        try {
            RoomMemoryStore(db,owners).insert(binding,InterestOperationEntity("intent","a",NODE,7,"LESS",bytes,1000))
            db.close(); db = Room.databaseBuilder(context,EmbyrDatabase::class.java,name).build()
            val store = RoomMemoryStore(db,owners)
            assertArrayEquals(bytes,store.unresolved(binding).single().canonicalPayload)
            owners.switchTo("b"); assertTrue(store.unresolved(owners.capture()).isEmpty())
            owners.switchTo("a")
            assertThrows(IllegalStateException::class.java) { runBlocking { store.unresolved(binding) } }
            assertEquals("UNCERTAIN",store.unresolved(owners.capture()).single().state)
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun deltaRollbackRecoveryStampAndProcessReopen() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>(); val name = "m705-world.db"
        context.deleteDatabase(name)
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        var db = Room.databaseBuilder(context,EmbyrDatabase::class.java,name).build()
        try {
            var store = RoomWorldStore(db,owners)
            val node = WorldNodeDto(NODE,ENTITY,1,REGION,0.5,0.5,0,"branching_tree","b".repeat(64),"SEED",2)
            val snapshot = WorldSnapshotDto(2,1,"a".repeat(64),listOf(WorldRegionDto(REGION,"discovery",null,0,0,1,1,"grove")),listOf(node),emptyList(),emptyList())
            val original = store.resync(binding,null,snapshot,1000)
            val changed = node.copy(growthState = "SPROUT",revision = 3)
            val page = WorldDeltaPageDto(2,3,3,false,listOf(WorldChangeDto(3,"NODE_GROWTH_CHANGED",NODE,NodePayloadDto("world-delta/v1",changed))))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER reject_m705_node BEFORE INSERT ON world_nodes BEGIN SELECT RAISE(ABORT,'test rollback'); END")
            assertThrows(android.database.sqlite.SQLiteConstraintException::class.java) { runBlocking { store.applyDelta(binding,original.stamp,page,2000) } }
            assertEquals(original,store.read(binding))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER reject_m705_node")
            store.applyDelta(binding,original.stamp,page,2000)
            db.close(); db = Room.databaseBuilder(context,EmbyrDatabase::class.java,name).build(); store = RoomWorldStore(db,owners)
            assertEquals("SPROUT",store.read(binding)!!.snapshot.nodes.single().growthState)
            val expected = store.stamp(binding)
            db.openHelper.writableDatabase.execSQL("UPDATE world_nodes SET payloadJson = 'corrupt' WHERE ownerId = 'a'")
            val empty = snapshot.copy(revision = 0,regions = emptyList(),nodes = emptyList())
            val recovered = store.resync(binding,expected,empty,3000)
            assertEquals(0L,recovered.snapshot.revision)
            assertThrows(IllegalArgumentException::class.java) { runBlocking { store.resync(binding,expected,snapshot,4000) } }
            owners.switchTo("b"); owners.switchTo("a")
            assertThrows(IllegalStateException::class.java) { runBlocking { store.resync(binding,recovered.stamp,snapshot,4000) } }
            assertEquals(recovered,store.read(owners.capture()))
        } finally { db.close(); context.deleteDatabase(name) }
    }
    companion object {
        const val NODE = "00000000-0000-0000-0000-000000000001"
        const val ENTITY = "00000000-0000-0000-0000-000000000002"
        const val REGION = "00000000-0000-0000-0000-000000000003"
    }
}

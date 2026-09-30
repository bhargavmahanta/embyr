package app.embyr.core.storage

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.RoomDatabase

@Dao
interface CommandDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(command: CommandEntity)

    @Query("SELECT * FROM commands WHERE ownerId = :ownerId AND id = :id")
    suspend fun get(ownerId: String, id: String): CommandEntity?

    @Query("SELECT * FROM commands WHERE ownerId = :ownerId AND state IN ('PENDING','IN_FLIGHT','AMBIGUOUS','EXPIRED') ORDER BY createdAtEpochMs")
    suspend fun unresolved(ownerId: String): List<CommandEntity>

    @Query("UPDATE commands SET state = :state, knownResultReference = :resultReference WHERE ownerId = :ownerId AND id = :id")
    suspend fun updateState(ownerId: String, id: String, state: String, resultReference: String?): Int

    @Query("UPDATE commands SET state = 'IN_FLIGHT', attempts = attempts + 1, lastAttemptAtEpochMs = :now WHERE ownerId = :ownerId AND id = :id")
    suspend fun markAttempt(ownerId: String, id: String, now: Long): Int
}

@Dao
interface WorldDao {
    @Query("SELECT * FROM world_meta WHERE ownerId = :ownerId")
    suspend fun meta(ownerId: String): WorldMetaEntity?

    @Query("SELECT * FROM world_regions WHERE ownerId = :ownerId ORDER BY objectId")
    suspend fun regions(ownerId: String): List<WorldRegionEntity>

    @Query("SELECT * FROM world_nodes WHERE ownerId = :ownerId ORDER BY objectId")
    suspend fun nodes(ownerId: String): List<WorldNodeEntity>

    @Query("SELECT * FROM world_aux WHERE ownerId = :ownerId")
    suspend fun aux(ownerId: String): WorldAuxEntity?

    @Query("DELETE FROM world_regions WHERE ownerId = :ownerId")
    suspend fun deleteRegions(ownerId: String)

    @Query("DELETE FROM world_nodes WHERE ownerId = :ownerId")
    suspend fun deleteNodes(ownerId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putMeta(meta: WorldMetaEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAux(aux: WorldAuxEntity)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun putRegions(regions: List<WorldRegionEntity>)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun putNodes(nodes: List<WorldNodeEntity>)
}

@Database(
    entities = [CommandEntity::class, WorldMetaEntity::class, WorldRegionEntity::class, WorldNodeEntity::class, WorldAuxEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class EmbyrDatabase : RoomDatabase() {
    abstract fun commandDao(): CommandDao
    abstract fun worldDao(): WorldDao
}

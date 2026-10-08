package app.embyr.core.storage

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json

@Entity(tableName = "exploration_state", primaryKeys = ["ownerId", "explorationId"])
data class ExplorationStateEntity(
    val ownerId: String, val explorationId: String, val detailJson: String? = null,
    val draft: String = "", val draftInitialized: Boolean = false, val lifecycleNeedsRefresh: Boolean = false,
    val editJson: String? = null, val editReflectionId: String? = null, val editState: String? = null,
)
@Entity(tableName = "assessment_state", primaryKeys = ["ownerId", "sessionId"])
data class AssessmentStateEntity(
    val ownerId: String, val sessionId: String, val explorationId: String,
    val sessionJson: String, val responseJson: String? = null, val responseId: String? = null,
    val knownRunId: String? = null, val selectedOptionId: String? = null,
)
@Entity(tableName = "activity_state", primaryKeys = ["ownerId"])
data class ActivityStateEntity(val ownerId: String, val explorationId: String? = null, val sessionId: String? = null)

@Entity(tableName = "learning_receipts", primaryKeys = ["ownerId", "commandId"])
data class LearningReceiptEntity(val ownerId: String, val commandId: String, val resultJson: String, val resultReference: String?)

@Dao interface LearningDao {
    @Query("SELECT * FROM learning_receipts WHERE ownerId = :owner AND commandId = :command") suspend fun receipt(owner: String, command: String): LearningReceiptEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putReceipt(row: LearningReceiptEntity)

    @Query("SELECT * FROM exploration_state WHERE ownerId = :owner AND explorationId = :id") suspend fun exploration(owner: String, id: String): ExplorationStateEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putExploration(row: ExplorationStateEntity)
    @Query("SELECT * FROM assessment_state WHERE ownerId = :owner AND sessionId = :id") suspend fun assessment(owner: String, id: String): AssessmentStateEntity?
    @Query("SELECT * FROM assessment_state WHERE ownerId = :owner AND explorationId = :exploration") suspend fun assessmentForExploration(owner: String, exploration: String): List<AssessmentStateEntity>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putAssessment(row: AssessmentStateEntity)
    @Query("SELECT * FROM activity_state WHERE ownerId = :owner") suspend fun activity(owner: String): ActivityStateEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putActivity(row: ActivityStateEntity)
}

interface LearningStore {
    suspend fun receipt(owner: String, command: String): LearningReceiptEntity?
    suspend fun putReceipt(row: LearningReceiptEntity)
    suspend fun exploration(owner: String, id: String): ExplorationStateEntity
    suspend fun updateExploration(owner: String, id: String, change: (ExplorationStateEntity) -> ExplorationStateEntity)
    suspend fun assessment(owner: String, id: String): AssessmentStateEntity?
    suspend fun assessmentForExploration(owner: String, exploration: String): List<AssessmentStateEntity>
    suspend fun updateAssessment(owner: String, id: String, change: (AssessmentStateEntity?) -> AssessmentStateEntity)
    suspend fun putAssessment(row: AssessmentStateEntity)
    suspend fun activity(owner: String): ActivityStateEntity
    suspend fun putActivity(row: ActivityStateEntity)
}

class RoomLearningStore(private val dao: LearningDao, private val owners: OwnerSession) : LearningStore {
    override suspend fun receipt(owner: String, command: String): LearningReceiptEntity? {
        checkOwner(owner); val row = dao.receipt(owner, command); checkOwner(owner); return row
    }
    override suspend fun putReceipt(row: LearningReceiptEntity) { checkOwner(row.ownerId); dao.putReceipt(row); checkOwner(row.ownerId) }
    private val mutex = Mutex()
    private fun checkOwner(owner: String) = check(owners.requireOwner() == owner)
    override suspend fun exploration(owner: String, id: String): ExplorationStateEntity {
        checkOwner(owner); val row = dao.exploration(owner, id); checkOwner(owner)
        return row ?: ExplorationStateEntity(owner, id)
    }
    override suspend fun updateExploration(owner: String, id: String, change: (ExplorationStateEntity) -> ExplorationStateEntity) = mutex.withLock {
        val next = change(exploration(owner, id)); check(next.ownerId == owner && next.explorationId == id)
        checkOwner(owner); dao.putExploration(next); checkOwner(owner)
    }
    override suspend fun assessment(owner: String, id: String): AssessmentStateEntity? {
        checkOwner(owner); val row = dao.assessment(owner, id); checkOwner(owner); return row
    }
    override suspend fun assessmentForExploration(owner: String, exploration: String): List<AssessmentStateEntity> {
        checkOwner(owner); val rows = dao.assessmentForExploration(owner,exploration); checkOwner(owner); return rows
    }
    override suspend fun updateAssessment(owner: String, id: String, change: (AssessmentStateEntity?) -> AssessmentStateEntity) = mutex.withLock {
        checkOwner(owner); val row = change(dao.assessment(owner,id)); checkOwner(owner)
        check(row.ownerId == owner && row.sessionId == id); dao.putAssessment(row); checkOwner(owner)
    }
    override suspend fun putAssessment(row: AssessmentStateEntity) = mutex.withLock { checkOwner(row.ownerId); dao.putAssessment(row); checkOwner(row.ownerId) }
    override suspend fun activity(owner: String): ActivityStateEntity {
        checkOwner(owner); val row = dao.activity(owner); checkOwner(owner); return row ?: ActivityStateEntity(owner)
    }
    override suspend fun putActivity(row: ActivityStateEntity) { checkOwner(row.ownerId); dao.putActivity(row); checkOwner(row.ownerId) }
}

/** Local persistence is serialized from public typed DTOs. */
object LearningJson { val codec = Json { ignoreUnknownKeys = true } }
fun ExplorationStateEntity.detail(): ExplorationDetailDto? = detailJson?.let { LearningJson.codec.decodeFromString(ExplorationDetailDto.serializer(), it) }
fun AssessmentStateEntity.session(): AssessmentSessionDto = LearningJson.codec.decodeFromString(AssessmentSessionDto.serializer(), sessionJson)
fun AssessmentStateEntity.response(): AssessmentResponseDto? = responseJson?.let { LearningJson.codec.decodeFromString(AssessmentResponseDto.serializer(), it) }

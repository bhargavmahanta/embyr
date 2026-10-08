package app.embyr

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import android.content.Context
import app.embyr.auth.OwnerSession
import app.embyr.core.storage.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class LearningStorageDeviceTest {
    @Test fun draftsReceiptsAndAssessmentReferencesSurviveReopenAndOwnerSwitch(): Unit = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>(); val name = "m704-owned-state.db"
        context.deleteDatabase(name)
        val owners = OwnerSession().apply { switchTo("a") }
        fun open() = Room.databaseBuilder(context,EmbyrDatabase::class.java,name).build()
        var db = open(); var store = RoomLearningStore(db.learningDao(),owners)
        store.updateExploration("a","exploration") { it.copy(draft = "Retained draft",draftInitialized = true,editJson = "{\"base_version\":2,\"text\":\"Submitted\"}",editReflectionId = "reflection",editState = "UNKNOWN") }
        store.putReceipt(LearningReceiptEntity("a","command","{\"response_id\":\"response\"}","response"))
        store.putAssessment(AssessmentStateEntity("a","session","exploration","{}",responseId = "response",knownRunId = "run",selectedOptionId = "option"))
        store.putActivity(ActivityStateEntity("a","exploration","session"))
        owners.switchTo("b"); store.updateExploration("b","exploration") { it.copy(draft = "Owner B",draftInitialized = true) }
        assertNull(store.receipt("b","command")); assertNull(store.assessment("b","session"))
        db.close(); db = open(); store = RoomLearningStore(db.learningDao(),owners)
        assertEquals("Owner B",store.exploration("b","exploration").draft)
        owners.switchTo("a")
        assertEquals("Retained draft",store.exploration("a","exploration").draft)
        assertEquals("UNKNOWN",store.exploration("a","exploration").editState)
        assertEquals("response",store.receipt("a","command")?.resultReference)
        assertEquals("run",store.assessment("a","session")?.knownRunId)
        assertEquals("session",store.activity("a").sessionId)
        db.close(); context.deleteDatabase(name)
    }
}

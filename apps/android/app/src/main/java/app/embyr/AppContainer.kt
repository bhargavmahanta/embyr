package app.embyr

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import app.embyr.core.storage.LearningCommands
import app.embyr.feature.exploration.ExplorationRepository
import app.embyr.feature.assessment.AssessmentRepository
import androidx.room.Room
import app.embyr.auth.AuthGateway
import app.embyr.auth.AuthSecretKind
import app.embyr.auth.KeystoreSessionStore
import app.embyr.auth.OwnerSession
import app.embyr.auth.SessionStore
import app.embyr.auth.SupabaseAuthGateway
import app.embyr.core.config.AppConfig
import app.embyr.core.config.BuildAppConfig
import app.embyr.core.logging.AndroidAppLogger
import app.embyr.core.logging.AppLogger
import app.embyr.core.network.EmbyrApi
import app.embyr.core.network.RetrofitEmbyrApi
import app.embyr.core.storage.CommandOutbox
import app.embyr.core.storage.CommandDispatcher
import app.embyr.core.storage.DataStoreUiPreferences
import app.embyr.core.storage.EmbyrDatabase
import app.embyr.core.storage.MIGRATION_1_2
import app.embyr.core.storage.MIGRATION_2_3
import app.embyr.core.storage.MIGRATION_3_4
import app.embyr.core.storage.RoomLearningStore
import app.embyr.core.storage.RoomCommandOutbox
import app.embyr.core.storage.RoomWorldStore
import app.embyr.core.storage.RoomJourneyStore
import app.embyr.core.storage.UiPreferences
import app.embyr.core.storage.WorldStore

class AppContainer(private val context: Context) {
    val config: AppConfig = BuildAppConfig()
    val logger: AppLogger = AndroidAppLogger()
    val ownerSession = OwnerSession()
    val sessionStore: SessionStore = KeystoreSessionStore(context)
    private val codeVerifierStore: SessionStore = KeystoreSessionStore(context, AuthSecretKind.CODE_VERIFIER)
    val authGateway: AuthGateway = SupabaseAuthGateway(config, sessionStore, codeVerifierStore, ownerSession)
    val embyrApi = RetrofitEmbyrApi(config, authGateway)
    val database: EmbyrDatabase = Room.databaseBuilder(
        context.applicationContext,
        EmbyrDatabase::class.java,
        "embyr-private.db",
    ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4).build()
    val commandOutbox: CommandOutbox = RoomCommandOutbox(database.commandDao(), ownerSession)
    val commandDispatcher = CommandDispatcher(commandOutbox, ownerSession)
    val learningStore = RoomLearningStore(database.learningDao(), ownerSession)
    val learningCommands = LearningCommands(commandOutbox, commandDispatcher, ownerSession, learningStore)
    val explorations = ExplorationRepository(embyrApi, ownerSession, learningStore, learningCommands)
    val assessments = AssessmentRepository(embyrApi, embyrApi, ownerSession, learningStore, learningCommands)
    fun isOnline(): Boolean {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val network = manager.activeNetwork ?: return false
        return manager.getNetworkCapabilities(network)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    }
    val journeyStore = RoomJourneyStore(database.journeyDao(), ownerSession)
    val worldStore: WorldStore = RoomWorldStore(database, ownerSession)
    val memoryStore = app.embyr.core.storage.RoomMemoryStore(database, ownerSession)
    val memory = app.embyr.feature.memory.MemoryRepository(embyrApi, ownerSession, memoryStore)
    val world = app.embyr.feature.world.WorldRepository(embyrApi, ownerSession, worldStore)
    suspend fun knownWorldNames(binding: app.embyr.auth.OwnerBinding): Map<Pair<String,Long>,String> {
        ownerSession.requireActive(binding)
        val rows = database.learningDao().knownExplorations(binding.ownerId)
        ownerSession.requireActive(binding)
        return rows.mapNotNull { row ->
            val detail = runCatching { row.detailJson?.let { app.embyr.core.storage.LearningJson.codec.decodeFromString(app.embyr.core.model.ExplorationDetailDto.serializer(), it) } }.getOrNull() ?: return@mapNotNull null
            val entity = detail.entity ?: return@mapNotNull null
            if (detail.id != row.explorationId || entity.id != detail.entityId || entity.entityVersion != detail.entityVersion) return@mapNotNull null
            (detail.entityId to detail.entityVersion) to entity.title
        }.toMap()
    }
    val uiPreferences: UiPreferences = DataStoreUiPreferences(context)
}

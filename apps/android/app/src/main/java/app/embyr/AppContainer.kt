package app.embyr

import android.content.Context
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
import app.embyr.core.storage.RoomCommandOutbox
import app.embyr.core.storage.RoomWorldStore
import app.embyr.core.storage.UiPreferences
import app.embyr.core.storage.WorldStore

class AppContainer(context: Context) {
    val config: AppConfig = BuildAppConfig()
    val logger: AppLogger = AndroidAppLogger()
    val ownerSession = OwnerSession()
    val sessionStore: SessionStore = KeystoreSessionStore(context)
    private val codeVerifierStore: SessionStore = KeystoreSessionStore(context, AuthSecretKind.CODE_VERIFIER)
    val authGateway: AuthGateway = SupabaseAuthGateway(config, sessionStore, codeVerifierStore, ownerSession)
    val embyrApi: EmbyrApi = RetrofitEmbyrApi(config, authGateway)
    val database: EmbyrDatabase = Room.databaseBuilder(
        context.applicationContext,
        EmbyrDatabase::class.java,
        "embyr-private.db",
    ).build()
    val commandOutbox: CommandOutbox = RoomCommandOutbox(database.commandDao(), ownerSession)
    val commandDispatcher = CommandDispatcher(commandOutbox, ownerSession)
    val worldStore: WorldStore = RoomWorldStore(database, ownerSession)
    val uiPreferences: UiPreferences = DataStoreUiPreferences(context)
}

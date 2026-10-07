package app.embyr.core.storage

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS `learning_receipts` (`ownerId` TEXT NOT NULL, `commandId` TEXT NOT NULL, `resultJson` TEXT NOT NULL, `resultReference` TEXT, PRIMARY KEY(`ownerId`, `commandId`))")
        db.execSQL("CREATE TABLE IF NOT EXISTS `exploration_state` (`ownerId` TEXT NOT NULL, `explorationId` TEXT NOT NULL, `detailJson` TEXT, `draft` TEXT NOT NULL, `draftInitialized` INTEGER NOT NULL, `lifecycleNeedsRefresh` INTEGER NOT NULL, `editJson` TEXT, `editReflectionId` TEXT, `editState` TEXT, PRIMARY KEY(`ownerId`, `explorationId`))")
        db.execSQL("CREATE TABLE IF NOT EXISTS `assessment_state` (`ownerId` TEXT NOT NULL, `sessionId` TEXT NOT NULL, `explorationId` TEXT NOT NULL, `sessionJson` TEXT NOT NULL, `responseJson` TEXT, `responseId` TEXT, `knownRunId` TEXT, `selectedOptionId` TEXT, PRIMARY KEY(`ownerId`, `sessionId`))")
        db.execSQL("CREATE TABLE IF NOT EXISTS `activity_state` (`ownerId` TEXT NOT NULL, `explorationId` TEXT, `sessionId` TEXT, PRIMARY KEY(`ownerId`))")
    }
}

package app.embyr.core.storage

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("""CREATE TABLE IF NOT EXISTS `journey_state` (`ownerId` TEXT NOT NULL, `draftStarterIdsJson` TEXT NOT NULL, `presentationJson` TEXT, `noResult` INTEGER NOT NULL, `acceptedExplorationId` TEXT, `acceptedRecommendationId` TEXT, `skippedRecommendationId` TEXT, PRIMARY KEY(`ownerId`))""")
    }
}

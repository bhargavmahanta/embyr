package app.embyr.core.storage

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE world_meta ADD COLUMN cacheGeneration INTEGER NOT NULL DEFAULT 0")
        db.execSQL("CREATE TABLE IF NOT EXISTS memory_cache (ownerId TEXT NOT NULL, summaryJson TEXT NOT NULL, fetchedAtEpochMs INTEGER NOT NULL, PRIMARY KEY(ownerId))")
        db.execSQL("CREATE TABLE IF NOT EXISTS interest_operations (id TEXT NOT NULL, ownerId TEXT NOT NULL, entityId TEXT NOT NULL, baseVersion INTEGER NOT NULL, preference TEXT NOT NULL, canonicalPayload BLOB NOT NULL, createdAtEpochMs INTEGER NOT NULL, state TEXT NOT NULL, acknowledgedVersion INTEGER, PRIMARY KEY(id))")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_interest_operations_ownerId_createdAtEpochMs ON interest_operations (ownerId, createdAtEpochMs)")
    }
}

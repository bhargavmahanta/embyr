package app.embyr.core.storage

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.uiDataStore by preferencesDataStore(name = "ui_preferences")

enum class ThemeChoice { SYSTEM, LIGHT, DARK }

interface UiPreferences {
    val theme: Flow<ThemeChoice>
    suspend fun setTheme(choice: ThemeChoice)
}

class DataStoreUiPreferences(context: Context) : UiPreferences {
    private val store = context.applicationContext.uiDataStore
    private val themeKey = stringPreferencesKey("theme")
    override val theme: Flow<ThemeChoice> = store.data.map { preferences ->
        preferences[themeKey]?.let { runCatching { ThemeChoice.valueOf(it) }.getOrNull() } ?: ThemeChoice.SYSTEM
    }
    override suspend fun setTheme(choice: ThemeChoice) {
        store.edit { it[themeKey] = choice.name }
    }
}

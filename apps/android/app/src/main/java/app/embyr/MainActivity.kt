package app.embyr

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.embyr.core.storage.ThemeChoice
import app.embyr.feature.shell.EmbyrApp
import app.embyr.feature.shell.ShellViewModel

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<ShellViewModel> {
        ShellViewModel.Factory((application as EmbyrApplication).container.authGateway)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val themeFlow = (application as EmbyrApplication).container.uiPreferences.theme
        setContent {
            val theme by themeFlow.collectAsStateWithLifecycle(initialValue = ThemeChoice.SYSTEM)
            EmbyrApp(viewModel, theme)
        }
    }
}

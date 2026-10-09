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
import app.embyr.feature.exploration.ExplorationViewModel
import app.embyr.feature.assessment.AssessmentViewModel

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<ShellViewModel> {
        ShellViewModel.Factory((application as EmbyrApplication).container)
    }

    private val explorations by viewModels<ExplorationViewModel> { ExplorationViewModel.Factory((application as EmbyrApplication).container) }
    private val assessments by viewModels<AssessmentViewModel> { AssessmentViewModel.Factory((application as EmbyrApplication).container) }

    private val memory by viewModels<app.embyr.feature.memory.MemoryViewModel> { app.embyr.feature.memory.MemoryViewModel.Factory((application as EmbyrApplication).container) }
    private val world by viewModels<app.embyr.feature.world.WorldViewModel> { app.embyr.feature.world.WorldViewModel.Factory((application as EmbyrApplication).container) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val themeFlow = (application as EmbyrApplication).container.uiPreferences.theme
        setContent {
            val theme by themeFlow.collectAsStateWithLifecycle(initialValue = ThemeChoice.SYSTEM)
            EmbyrApp(viewModel, theme, explorations, assessments, memory, world)
        }
    }
}

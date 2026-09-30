package app.embyr.feature.shell

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import app.embyr.auth.AuthState
import app.embyr.navigation.BootstrapRoute
import app.embyr.navigation.ReadyShellRoute
import app.embyr.navigation.SignedOutRoute
import app.embyr.core.storage.ThemeChoice

@Composable
fun EmbyrApp(viewModel: ShellViewModel, theme: ThemeChoice = ThemeChoice.SYSTEM) {
    val authState by viewModel.authState.collectAsStateWithLifecycle()
    val isDark = when (theme) {
        ThemeChoice.DARK -> true
        ThemeChoice.LIGHT -> false
        ThemeChoice.SYSTEM -> androidx.compose.foundation.isSystemInDarkTheme()
    }
    MaterialTheme(colorScheme = if (isDark) darkColorScheme() else lightColorScheme()) {
        val navController = rememberNavController()
        LaunchedEffect(authState) {
            if (authState == AuthState.SignedOut) {
                navController.navigate(SignedOutRoute) { popUpTo<BootstrapRoute> { inclusive = false }; launchSingleTop = true }
            }
        }
        Surface(Modifier.fillMaxSize()) {
            NavHost(navController, startDestination = BootstrapRoute) {
                composable<BootstrapRoute> {
                    ShellPlaceholder("Checking session", "Authentication and profile entry arrive in M7-03") {
                        Button(onClick = { navController.navigate(ReadyShellRoute) }) { Text("View navigation preview") }
                    }
                }
                composable<SignedOutRoute> {
                    ShellPlaceholder("Signed out", "Sign-in is planned for M7-03") {
                        Button(onClick = { navController.navigate(ReadyShellRoute) }) { Text("View navigation preview") }
                    }
                }
                composable<ReadyShellRoute> {
                    ShellPlaceholder("Shell preview", "No private learner data is available in this placeholder") {
                        Button(onClick = { navController.navigate(SignedOutRoute) }) { Text("Back to signed-out placeholder") }
                    }
                }
            }
        }
    }
}

@Composable
private fun ShellPlaceholder(title: String, description: String, action: @Composable () -> Unit) {
    Scaffold { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(title, style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
            Text(description, style = MaterialTheme.typography.bodyLarge)
            action()
        }
    }
}

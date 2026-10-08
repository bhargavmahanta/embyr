package app.embyr.feature.shell

import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import app.embyr.core.storage.ThemeChoice
import app.embyr.feature.exploration.*
import app.embyr.feature.assessment.*
import app.embyr.navigation.ExplorationListRoute
import app.embyr.navigation.ExplorationDetailRoute
import app.embyr.navigation.AssessmentRoute
import app.embyr.navigation.MemoryRoute
import app.embyr.navigation.WorldRoute
import app.embyr.feature.memory.*
import app.embyr.feature.world.*
import androidx.activity.compose.BackHandler
import androidx.navigation.toRoute
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.lifecycle.compose.LifecycleStartEffect
import app.embyr.navigation.BootstrapRoute
import app.embyr.navigation.ExplorationReadyRoute
import app.embyr.navigation.OnboardingRoute
import app.embyr.navigation.ReadyShellRoute
import app.embyr.navigation.RecommendationRoute
import app.embyr.navigation.RecoverableErrorRoute
import app.embyr.navigation.SignedOutRoute

@Composable
fun EmbyrApp(viewModel: ShellViewModel, theme: ThemeChoice = ThemeChoice.SYSTEM, explorations: ExplorationViewModel? = null, assessments: AssessmentViewModel? = null, memory: MemoryViewModel? = null, world: WorldViewModel? = null) {
    val ui by viewModel.ui.collectAsStateWithLifecycle()
    JourneyContent(ui, viewModel, theme, explorations, assessments, memory, world)
}

@Composable
fun JourneyContent(ui: JourneyUiState, viewModel: JourneyActions, theme: ThemeChoice = ThemeChoice.SYSTEM, explorations: ExplorationViewModel? = null, assessments: AssessmentViewModel? = null, memory: MemoryViewModel? = null, world: WorldViewModel? = null) {
    val dark = when (theme) {
        ThemeChoice.DARK -> true
        ThemeChoice.LIGHT -> false
        ThemeChoice.SYSTEM -> androidx.compose.foundation.isSystemInDarkTheme()
    }
    MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
        val nav = rememberNavController()
        val explorationState = explorations?.ui?.collectAsStateWithLifecycle()?.value
        val activeOwner = explorations?.activeOwner?.collectAsStateWithLifecycle()?.value
        val assessmentState = assessments?.ui?.collectAsStateWithLifecycle()?.value
        val memoryState = memory?.ui?.collectAsStateWithLifecycle()?.value
        val worldState = world?.ui?.collectAsStateWithLifecycle()?.value
        val binding = memory?.activeBinding?.collectAsStateWithLifecycle()?.value
        val memoryBound = binding != null && binding.ownerId == ui.profile?.id && memoryState?.binding == binding
        val worldBound = binding != null && binding.ownerId == ui.profile?.id && worldState?.binding == binding
        val featureBound = activeOwner != null && activeOwner == ui.profile?.id && explorationState?.owner == activeOwner
        LaunchedEffect(ui.screen, ui.profile?.id) {
            when (ui.screen) {
                JourneyScreen.RESTORING -> Unit
                JourneyScreen.SIGNED_OUT -> nav.replaceRoot(SignedOutRoute)
                JourneyScreen.ONBOARDING -> nav.replaceRoot(OnboardingRoute)
                JourneyScreen.ENTRY -> nav.replaceRoot(ReadyShellRoute)
                JourneyScreen.RECOMMENDATION -> nav.replaceRoot(RecommendationRoute)
                JourneyScreen.EXPLORATION_READY -> nav.replaceRoot(ExplorationReadyRoute)
                JourneyScreen.RECOVERABLE_ERROR -> nav.replaceRoot(RecoverableErrorRoute)
            }
        }
        LaunchedEffect(ui.screen, featureBound, explorationState?.restoreExploration, explorationState?.restoreSession) {
            if (featureBound && ui.screen == JourneyScreen.ENTRY && explorationState?.restoreExploration != null) {
                val id = explorationState.restoreExploration
                nav.navigate(ExplorationDetailRoute(id)) { launchSingleTop = true }
                explorationState.restoreSession?.let { nav.navigate(AssessmentRoute(it)) { launchSingleTop = true } }
                explorations?.consumeRestore()
            }
        }
        Surface(Modifier.fillMaxSize()) {
            NavHost(nav, startDestination = BootstrapRoute) {
                composable<BootstrapRoute> { SimplePage("Checking your session") { Text("Preparing your space…") } }
                composable<SignedOutRoute> { SignedOutPage(ui, viewModel) }
                composable<OnboardingRoute> { OnboardingPage(ui, viewModel) }
                composable<ReadyShellRoute> {
                    EntryPage(ui, viewModel, browse = if (featureBound) ({ nav.navigate(ExplorationListRoute) }) else null,
                        open = if (featureBound) ({ id -> nav.navigate(ExplorationDetailRoute(id)) }) else null,
                        memory = if(memoryBound) ({ nav.navigate(MemoryRoute) }) else null,
                        world = if(worldBound) ({ nav.navigate(WorldRoute) }) else null)
                }
                composable<MemoryRoute> {
                    BackHandler { viewModel.backToEntry(); nav.replaceRoot(ReadyShellRoute) }
                    if(memoryBound && memory != null && memoryState != null) {
                        LaunchedEffect(binding) { memory.open() }
                        MemoryScreen(memoryState,memory::refresh,memory::put,memory::applySaved,memory::adopt,
                            { viewModel.backToEntry(); nav.replaceRoot(ReadyShellRoute) })
                    } else SimplePage("Checking your session") { Text("Preparing your space…") }
                }
                composable<WorldRoute> {
                    BackHandler { viewModel.backToEntry(); nav.replaceRoot(ReadyShellRoute) }
                    if(worldBound && world != null && worldState != null) {
                        LaunchedEffect(binding) { world.open() }
                        WorldScreen(worldState,world::refresh,{ viewModel.backToEntry(); nav.replaceRoot(ReadyShellRoute) })
                    } else SimplePage("Checking your session") { Text("Preparing your space…") }
                }
                composable<RecommendationRoute> { RecommendationPage(ui, viewModel) }
                composable<ExplorationReadyRoute> {
                    if (featureBound && ui.acceptedExplorationId != null) {
                        LaunchedEffect(ui.acceptedExplorationId) { nav.navigate(ExplorationDetailRoute(ui.acceptedExplorationId)) { launchSingleTop = true } }
                    } else ReadyPage(ui, viewModel)
                }
                composable<ExplorationListRoute> {
                    if (featureBound && explorations != null && explorationState != null) {
                        LaunchedEffect(activeOwner) { explorations.list() }
                        ExplorationListScreen(explorationState, { nav.navigate(ExplorationDetailRoute(it)) }, explorations::list, explorations::more, { viewModel.backToEntry(); nav.replaceRoot(ReadyShellRoute) })
                    } else SimplePage("Checking your session") { Text("Preparing your space…") }
                }
                composable<ExplorationDetailRoute> { entry ->
                    val route = entry.toRoute<ExplorationDetailRoute>()
                    if (featureBound && explorations != null && explorationState != null) {
                        LaunchedEffect(activeOwner,route.id) { explorations.open(route.id) }
                        DisposableEffect(activeOwner,route.id,assessmentState?.owner) {
                            if (assessmentState?.owner == activeOwner) assessments?.bindExploration(route.id)
                            onDispose { assessments?.unbindExploration(route.id) }
                        }
                        ExplorationDetailScreen(if (assessmentState != null) explorationState.withAssessmentStart(assessmentState) else explorationState, explorations::refresh, explorations::deliver, explorations::action,
                            explorations::complete, explorations::recover, explorations::setDraft, explorations::saveReflection, explorations::recheckEdit,
                            { nav.navigate(AssessmentRoute(it)) }, { confidence -> assessments?.start(route.id,confidence) { nav.openCheckFromDetail(route.id,it) } },
                            { assessments?.recoverStart(route.id) { nav.openCheckFromDetail(route.id,it) } },
                            { explorations.list(); nav.navigate(ExplorationListRoute) { popUpTo<ExplorationListRoute> { inclusive = true }; launchSingleTop = true } })
                    } else SimplePage("Checking your session") { Text("Preparing your space…") }
                }
                composable<AssessmentRoute> { entry ->
                    val route = entry.toRoute<AssessmentRoute>()
                    if (featureBound && assessments != null && assessmentState?.owner == activeOwner) {
                        LaunchedEffect(activeOwner,route.id) { assessments.open(route.id) }
                        LifecycleStartEffect(activeOwner,route.id) {
                            assessments.foreground(true)
                            onStopOrDispose { assessments.foreground(false) }
                        }
                        if (assessmentState.requestedSessionId == route.id) AssessmentScreen(assessmentState, assessments::support, assessments::answer, assessments::retry, assessments::recheck,
                            { assessments.leave { explorations?.refresh(); nav.popBackStack() } })
                        else SimplePage("Opening optional check") { Text("Fetching this check…") }
                    } else SimplePage("Checking your session") { Text("Preparing your space…") }
                }
                composable<RecoverableErrorRoute> {
                    SimplePage("Could not finish signing in") {
                        Status(ui)
                        Button(onClick = viewModel::retryStartup, enabled = !ui.busy) { Text("Retry") }
                        OutlinedButton(onClick = viewModel::signOut) { Text("Sign out") }
                    }
                }
            }
        }
    }
}

private fun NavHostController.openCheckFromDetail(explorationId: String, sessionId: String) {
    val entry = currentBackStackEntry ?: return
    if (entry.destination.hasRoute<ExplorationDetailRoute>() && entry.toRoute<ExplorationDetailRoute>().id == explorationId) {
        navigate(AssessmentRoute(sessionId))
    }
}

private fun NavHostController.replaceRoot(route: Any) {
    navigate(route) {
        popUpTo(graph.id) { inclusive = false }
        launchSingleTop = true
    }
}

@Composable
private fun SignedOutPage(ui: JourneyUiState, viewModel: JourneyActions) {
    SimplePage("Sign in") {
        Text("Use the email address invited to the internal alpha.")
        OutlinedTextField(
            value = ui.email, onValueChange = viewModel::setEmail, label = { Text("Email address") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            singleLine = true, modifier = Modifier.fillMaxWidth(), enabled = !ui.busy,
        )
        if (ui.awaitingCode) {
            OutlinedTextField(
                value = ui.code, onValueChange = viewModel::setCode, label = { Text("Email code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                singleLine = true, modifier = Modifier.fillMaxWidth(), enabled = !ui.busy,
            )
            Button(onClick = viewModel::verifyCode, enabled = !ui.busy && ui.code.isNotBlank()) { Text("Verify code") }
            OutlinedButton(onClick = viewModel::sendCode, enabled = !ui.busy) { Text("Resend code") }
        } else Button(onClick = viewModel::sendCode, enabled = !ui.busy && ui.email.isNotBlank()) { Text("Send code") }
        Status(ui)
    }
}

@Composable
private fun OnboardingPage(ui: JourneyUiState, viewModel: JourneyActions) {
    Scaffold { inset ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(inset).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Heading("Choose starter interests") }
            item { OutlinedButton(onClick = viewModel::signOut) { Text("Sign out") } }
            item { Text("Choose up to 20, or continue with none. You can change direction later.") }
            item { Text("${ui.selectedIds.size} of 20 selected") }
            item { Status(ui) }
            if (ui.starters.isEmpty()) item {
                OutlinedButton(onClick = viewModel::retryStarters, enabled = !ui.busy) { Text("Refresh interests") }
            }
            items(ui.starters, key = { it.id }) { starter ->
                val checked = starter.id in ui.selectedIds
                Row(
                    modifier = Modifier.fillMaxWidth().testTag("starter-${starter.id}").toggleable(
                        value = checked,
                        enabled = !ui.busy && !ui.onboardingPending,
                        role = Role.Checkbox,
                        onValueChange = { viewModel.toggleStarter(starter.id) },
                    ).padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Checkbox(checked = checked, onCheckedChange = null, enabled = !ui.busy && !ui.onboardingPending)
                    Column { Text(starter.title, style = MaterialTheme.typography.titleMedium); Text(starter.summary) }
                }
            }
            item {
                Button(onClick = { viewModel.submitOnboarding(ui.unresolved) }, enabled = !ui.busy) {
                    Text(if (ui.unresolved) "Start a new attempt" else if (ui.onboardingPending) "Check submission" else "Continue")
                }
            }
        }
    }
}

@Composable
private fun EntryPage(ui: JourneyUiState, viewModel: JourneyActions, browse: (() -> Unit)? = null, open: ((String) -> Unit)? = null, memory: (() -> Unit)? = null, world: (() -> Unit)? = null) {
    SimplePage("Ready to explore") {
        Text("Choose how to find your next exploration.")
        if (ui.explorations.isEmpty()) Text("No explorations yet.")
        else Text("${ui.explorations.size} recent explorations")
        Button(onClick = { viewModel.requestRecommendation("EXPLORE") }, enabled = !ui.busy) { Text("Explore") }
        OutlinedButton(onClick = { viewModel.requestRecommendation("SURPRISE") }, enabled = !ui.busy) { Text("Surprise me") }
        if (ui.recommendation != null || ui.noResult) {
            OutlinedButton(onClick = viewModel::showLatestRecommendation, enabled = !ui.busy) { Text("View latest suggestion") }
        }
        memory?.let { OutlinedButton(onClick = it,enabled = !ui.busy) { Text("Your Memory") } }
        world?.let { OutlinedButton(onClick = it,enabled = !ui.busy) { Text("Your World") } }
        browse?.let { OutlinedButton(onClick = it, enabled = !ui.busy) { Text("Your explorations") } }
        if (ui.acceptedExplorationId != null) {
            OutlinedButton(onClick = { if (open != null) open(ui.acceptedExplorationId) else viewModel.showExplorationReady() }, enabled = !ui.busy) { Text("Exploration ready") }
        }
        Status(ui)
        OutlinedButton(onClick = viewModel::refreshEntry, enabled = !ui.busy) { Text("Refresh") }
        OutlinedButton(onClick = viewModel::signOut) { Text("Sign out") }
    }
}

@Composable
private fun RecommendationPage(ui: JourneyUiState, viewModel: JourneyActions) {
    SimplePage("Your suggestion") {
        val recommendation = ui.recommendation
        when {
            recommendation != null -> {
                Text(recommendation.entity.title, style = MaterialTheme.typography.titleLarge)
                recommendation.hook?.let { Text(it) }
                recommendation.reason?.let { Text(it) }
                Text("Mode: ${recommendation.mode.lowercase().replaceFirstChar { it.uppercase() }}")
                Button(onClick = { viewModel.decide("ACCEPT") }, enabled = !ui.busy && !ui.unresolved && !ui.decisionOutstanding) { Text("Accept") }
                OutlinedButton(onClick = { viewModel.decide("SKIP") }, enabled = !ui.busy && !ui.unresolved && !ui.decisionOutstanding) { Text("Skip") }
            }
            ui.noResult -> Text("Nothing fits this mode right now. You can choose another mode whenever you like.")
            else -> Text("Checking your request…")
        }
        Status(ui)
        if (ui.decisionOutstanding) {
            Text("The previous decision has not been confirmed. Keep its original request while checking.")
            OutlinedButton(onClick = viewModel::retryDecision, enabled = !ui.busy) { Text("Check decision again") }
        } else if (ui.recommendationPending) {
            OutlinedButton(onClick = viewModel::retryGeneration, enabled = !ui.busy) { Text("Check request again") }
        } else if (ui.unresolved) {
            Text("A previous request is unresolved. A new request is a separate action.")
            OutlinedButton(onClick = { viewModel.requestRecommendation("EXPLORE", true) }, enabled = !ui.busy) { Text("Start a new Explore request") }
            OutlinedButton(onClick = { viewModel.requestRecommendation("SURPRISE", true) }, enabled = !ui.busy) { Text("Start a new Surprise request") }
        } else if (ui.noResult) {
            OutlinedButton(onClick = { viewModel.requestRecommendation("EXPLORE") }, enabled = !ui.busy) { Text("Try Explore") }
            OutlinedButton(onClick = { viewModel.requestRecommendation("SURPRISE") }, enabled = !ui.busy) { Text("Try Surprise") }
        }
        OutlinedButton(onClick = viewModel::backToEntry, enabled = !ui.busy) { Text("Back to entry") }
    }
}

@Composable
private fun ReadyPage(ui: JourneyUiState, viewModel: JourneyActions) {
    SimplePage("Exploration ready") {
        Text("Your exploration is ready. You can return to the entry screen.")
        Status(ui)
        Button(onClick = viewModel::backToEntry, enabled = !ui.busy) { Text("Back to entry") }
    }
}

@Composable
private fun SimplePage(title: String, content: @Composable () -> Unit) {
    Scaffold { inset ->
        Column(
            modifier = Modifier.fillMaxSize().padding(inset).verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Heading(title)
            content()
        }
    }
}

@Composable
private fun Heading(title: String) {
    Text(title, style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
}

@Composable
private fun Status(ui: JourneyUiState) {
    if (ui.busy) Text("Working…")
    ui.message?.let { Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
}

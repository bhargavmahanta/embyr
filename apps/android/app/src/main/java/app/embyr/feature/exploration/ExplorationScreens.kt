package app.embyr.feature.exploration

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp

@Composable fun LearningPage(title: String, content: @Composable ColumnScope.() -> Unit) {
    Scaffold { inset -> Column(Modifier.fillMaxSize().padding(inset).verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
        content()
    } }
}
@Composable fun LearningStatus(busy: Boolean, message: String?) {
    if (busy) Text("Working…")
    message?.let { Text(it, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
}
@Composable fun ExplorationListScreen(state: ExplorationUiState, open: (String) -> Unit, refresh: () -> Unit, more: () -> Unit, back: () -> Unit) {
    BackHandler(onBack = back)
    LearningPage("Your explorations") {
        LearningStatus(state.busy,state.message)
        if (state.items.isEmpty() && !state.busy) Text("No explorations yet. Accept a suggestion to begin.")
        state.items.forEach { item ->
            OutlinedButton(onClick = { open(item.id) }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("${item.learningIntent.lowercase().replace('_',' ')} • ${item.status.lowercase()}")
            }
        }
        if (state.nextCursor != null) OutlinedButton(onClick = more, enabled = !state.busy) { Text("Load more") }
        OutlinedButton(onClick = refresh, enabled = !state.busy) { Text("Refresh explorations") }
        OutlinedButton(onClick = back) { Text("Back to entry") }
    }
}
@Composable fun ExplorationDetailScreen(
    state: ExplorationUiState, refresh: () -> Unit, deliver: () -> Unit, action: (String) -> Unit,
    complete: () -> Unit, recover: () -> Unit, draft: (String) -> Unit, save: (Boolean) -> Unit, recheck: () -> Unit,
    assessment: (String) -> Unit, startAssessment: (String) -> Unit, recoverStart: () -> Unit, back: () -> Unit,
) {
    BackHandler(onBack = back)
    var confidence by rememberSaveable(state.selected) { mutableStateOf<String?>(null) }
    var confirm by rememberSaveable(state.selected) { mutableStateOf(false) }
    LearningPage(state.detail?.entity?.title ?: "Exploration") {
        LearningStatus(state.busy,state.message)
        if (state.pendingOperations.isNotEmpty()) {
            Text("Saved request needs checking: ${state.pendingOperations.joinToString(", ")}")
            OutlinedButton(onClick = recover, enabled = !state.busy) { Text("Check saved request") }
        }
        if (state.assessmentStartPending) OutlinedButton(onClick = recoverStart, enabled = !state.busy) { Text("Check saved check start") }
        if (state.lifecycleNeedsRefresh) Text("Reviewed work is retained. Refresh before changing the lifecycle.")
        val detail = state.detail
        if (detail != null) {
            Text("Status: ${detail.status.lowercase()}")
            detail.entity?.let { Text(it.summary) }
            val delivery = detail.delivery
            if (delivery == null) {
                Text("Prepare the reviewed work for this accepted exploration.")
                Button(onClick = deliver, enabled = !state.busy) { Text("Prepare reviewed work") }
            } else {
                Text("Reviewed work", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                Text(delivery.workPrompt); Text(delivery.effortGuidance)
                delivery.searchNudges.forEach { Text(it) }
                Text(delivery.reflectionPrompt)
            }
            if (detail.status != "COMPLETED") {
                OutlinedButton(onClick = { action("RETURN") }, enabled = !state.busy && !state.lifecycleNeedsRefresh) { Text("Return to this exploration") }
                if (detail.status == "ACTIVE") OutlinedButton(onClick = { action("PAUSE") }, enabled = !state.busy && !state.lifecycleNeedsRefresh) { Text("Pause exploration") }
                if (detail.status == "PAUSED") Button(onClick = { action("RESUME") }, enabled = !state.busy && !state.lifecycleNeedsRefresh) { Text("Resume exploration") }
                Button(onClick = { confirm = true }, enabled = !state.busy && !state.lifecycleNeedsRefresh) { Text("Mark exploration complete") }
                Text("Completion records your intent. The optional check is independent.")
            } else Text("Completed. You can still reflect and read any late check feedback.")
            OutlinedTextField(value = state.draft, onValueChange = draft, label = { Text("Your reflection") }, enabled = !state.busy, modifier = Modifier.fillMaxWidth(), minLines = 3)
            Text("${state.draft.length} / 10000 characters")
            if (state.editOutstanding) {
                detail.reflection?.let { Text("Current server reflection: ${it.text}") }
                OutlinedButton(onClick = recheck, enabled = !state.busy) { Text("Check previous edit") }
                Button(onClick = { save(true) }, enabled = !state.busy && state.draft.isNotBlank()) { Text("Apply draft to reviewed version") }
            } else Button(onClick = { save(false) }, enabled = !state.busy && state.draft.isNotBlank()) { Text(if (detail.reflection == null) "Save reflection" else "Save reflection edit") }
            val session = detail.assessmentSession
            if (session != null) Button(onClick = { assessment(session.id) }, enabled = !state.busy) { Text("Open optional check") }
            else if (detail.status == "ACTIVE" && delivery != null) {
                Text("Optional check", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                Text("How does this feel before checking?")
                listOf("FUZZY" to "Still fuzzy", "MAIN_IDEA" to "I have the main idea", "COULD_EXPLAIN" to "I could explain it", "CHALLENGE_ME" to "Challenge me").forEach { (value,label) ->
                    OutlinedButton(onClick = { confidence = value }, enabled = !state.busy, modifier = Modifier.semantics { selected = confidence == value }) { Text(label) }
                }
                Button(onClick = { confidence?.let(startAssessment) }, enabled = !state.busy && confidence != null) { Text("Start optional check") }
            }
        }
        OutlinedButton(onClick = refresh, enabled = !state.busy) { Text("Refresh exploration") }
        OutlinedButton(onClick = back) { Text("Back to explorations") }
    }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text("Mark complete?") }, text = { Text("You can complete without an assessment. Any submitted check can finish later; completion does not imply mastery.") }, confirmButton = { TextButton(onClick = { confirm = false; complete() }) { Text("Confirm completion") } }, dismissButton = { TextButton(onClick = { confirm = false }) { Text("Keep exploring") } })
}

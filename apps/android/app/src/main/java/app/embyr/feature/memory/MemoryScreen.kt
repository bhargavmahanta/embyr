package app.embyr.feature.memory

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import app.embyr.core.model.*
import app.embyr.core.network.TransportError
import java.time.Instant

@Composable
fun MemoryScreen(ui: MemoryUiState, refresh: () -> Unit, put: (ExplicitInterestDto,String) -> Unit, applySaved: (String) -> Unit, adopt: (String) -> Unit, back: () -> Unit) {
    Scaffold { inset -> Column(Modifier.fillMaxSize().padding(inset).verticalScroll(rememberScrollState()).padding(24.dp),verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Your Memory",style = MaterialTheme.typography.headlineMedium,modifier = Modifier.semantics { heading() })
        OutlinedButton(onClick = back) { Text("Back to entry") }
        Button(onClick = refresh,enabled = !ui.busy) { Text("Refresh Memory") }
        if(ui.busy) Text("Checking Memory…")
        ui.message?.let { Text(it,modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
        val read = ui.read
        if (read?.error != null) Text(if(read.error is TransportError.Authentication) "Sign in again to refresh Memory." else "Could not refresh. You can try again.",modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        val memory = read?.summary
        if(memory == null) Text("No saved Memory is available. Refresh when connected.")
        else {
            Text(if(read.fresh) "Current server read" else "Saved copy${read.fetchedAt?.let { " from ${Instant.ofEpochMilli(it)}" } ?: ""}")
            Text("Projection: ${memory.projection.status}",modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            when(memory.projection.status) {
                "PENDING" -> Text("Recent activity is still being processed.")
                "FAILED" -> Text("Processing has failed. Recorded choices and available facts are shown; refresh to check recovery.")
            }
            Text("Learning preferences",style = MaterialTheme.typography.titleLarge,modifier = Modifier.semantics { heading() })
            memory.learningPreferences?.let { Text("Adventure: ${it.adventurePreference}\nEffort: ${it.preferredEffort}\nSupport: ${it.supportStyle}\nPractical activities: ${if(it.practicalOptIn) "opted in" else "not opted in"}") } ?: Text("No recorded learning preferences.")
            Text("Explicit interests",style = MaterialTheme.typography.titleLarge,modifier = Modifier.semantics { heading() })
            if(memory.explicitInterests.isEmpty()) Text("No explicit choices in this summary.")
            memory.explicitInterests.forEach { choice ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp),verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(choice.title ?: "Interest ${choice.entityId} — unavailable",style = MaterialTheme.typography.titleMedium)
                    Text("Saved choice: ${preferenceLabel(choice.preference)} · version ${choice.version}")
                    if(choice.availability == "UNAVAILABLE") Text("This content is unavailable. Your saved preference remains recorded.")
                    val pending = read.operations.any { it.entityId == choice.entityId }
                    M6Contract.preferences.forEach { preference ->
                        OutlinedButton(onClick = { put(choice,preference) },enabled = !ui.busy && !pending && preference != choice.preference,
                            modifier = Modifier.fillMaxWidth().semantics { selected = choice.preference == preference }) { Text(preferenceLabel(preference)) }
                    }
                } }
            }
            if(memory.truncated.explicitInterests) Text("This summary contains only the 20 most recent explicit choices. Missing choices are unresolved, not absent.")
            Text("Exploration facts",style = MaterialTheme.typography.titleLarge,modifier = Modifier.semantics { heading() })
            memory.recentlyExplored.forEach { Text("${it.title}\nStarted ${it.startedCount} · Returned ${it.returnedCount} · Completed ${it.completedCount}") }
            if(memory.recentlyExplored.isEmpty()) Text("No recent Exploration facts.")
            if(memory.truncated.recentlyExplored) Text("Showing only 10 recent entries.")
            Text("Recognition evidence",style = MaterialTheme.typography.titleLarge,modifier = Modifier.semantics { heading() })
            memory.recognitionEvidence.forEachIndexed { index,evidence -> Text("Record ${index+1}: ${evidence.summary}\n${evidence.evidenceCount} recorded responses · ${if(evidence.supportRequired) "support used" else "no support recorded"}") }
            if(memory.recognitionEvidence.isEmpty()) Text("No recognition evidence in this summary.")
            if(memory.truncated.recognitionEvidence) Text("Showing only 10 recognition summaries.")
        }
        if(read != null) {
            read.operations.forEach { operation ->
                val current = read.summary?.explicitInterests?.find { it.entityId == operation.entityId }
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp),verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Saved intent for: ${current?.title ?: "name unavailable"}",style = MaterialTheme.typography.titleMedium)
                    Text("Interest reference: ${operation.entityId}")
                    Text("Saved intent: ${preferenceLabel(operation.preference)} · observed version ${operation.baseVersion}")
                    Text(when(operation.state) { "CONFLICT" -> "A newer choice conflicted with this request."; "REJECTED" -> "This request was rejected. It has not been resent."; else -> "This request has no confirmed result. It has not been resent." })
                    Text(current?.let { "Current choice: ${preferenceLabel(it.preference)} · version ${it.version}. A match does not confirm the original request." } ?: "This choice is outside the bounded summary. Keep the saved intent and refresh later.")
                    OutlinedButton(onClick = { refresh() },enabled = !ui.busy) { Text("Read current choices") }
                    Button(onClick = { applySaved(operation.id) },enabled = !ui.busy && read.fresh && current != null) { Text("Apply saved intent to current version") }
                    OutlinedButton(onClick = { adopt(operation.id) },enabled = !ui.busy && read.fresh && current != null) { Text("Adopt current choice") }
                } }
            }
        }

    } }
}
fun preferenceLabel(value: String) = when(value) { "NEUTRAL" -> "Neutral"; "MORE" -> "More"; "LESS" -> "Less"; "PAUSED" -> "Paused"; "NOT_INTERESTED" -> "Not interested"; else -> "Unavailable choice" }

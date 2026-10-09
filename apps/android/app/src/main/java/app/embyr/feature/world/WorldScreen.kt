package app.embyr.feature.world

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import app.embyr.core.network.TransportError

@Composable
fun WorldScreen(ui: WorldUiState, refresh: () -> Unit, back: () -> Unit) {
    val read = ui.read
    val snapshot = read?.cache?.snapshot
    Scaffold { inset -> NativeForest(snapshot?.nodes ?: emptyList(),ui.names,Modifier.fillMaxSize().padding(inset).padding(24.dp),snapshot != null) {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Your World",style = MaterialTheme.typography.headlineMedium,modifier = Modifier.semantics { heading() })
            OutlinedButton(onClick = back) { Text("Back to entry") }
            Button(onClick = refresh,enabled = !ui.busy) { Text(if(ui.read?.more == true) "Continue World refresh" else "Refresh World") }
            if(ui.busy) Text("Checking World…")
            ui.message?.let { Text(it,modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
            read?.error?.let { Text(if(it is TransportError.Authentication) "Sign in again to refresh World." else "Could not refresh this World. Try again when connected.",modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
            if(snapshot == null) Text("No saved World is available. Refresh when connected.")
            else {
                Text(if(read.fresh) "Current server read" else "Saved World; refresh to check for changes.")
                if(read.more) Text("More changes remain. Continue when ready.")
                if(snapshot.nodes.isEmpty()) Text("Your forest is quiet. Recorded Exploration encounters will appear here after processing.")
            }
        }
    } }
}

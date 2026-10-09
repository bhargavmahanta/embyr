package app.embyr

import androidx.activity.compose.setContent
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.fillMaxSize
import app.embyr.core.model.WorldNodeDto
import app.embyr.feature.world.NativeForest
import java.security.MessageDigest
import java.util.ArrayList
import java.util.Collections
import java.util.Locale

/** Test APK only: production NativeForest, deterministic synthetic scene, no persistence/API. */
object ForestReleaseProbe {
    @JvmStatic fun present(activity: MainActivity) {
        val count = 100
        val nodes = ArrayList<WorldNodeDto>(count)
        for (i in 0 until count) {
            val bytes = MessageDigest.getInstance("SHA-256").digest("m705-synthetic-$i".toByteArray(Charsets.UTF_8))
            val hex = StringBuilder()
            for (value in bytes) hex.append(String.format(Locale.ROOT, "%02x", value.toInt() and 255))
            nodes.add(WorldNodeDto(
                String.format(Locale.ROOT,"%08x-0000-4000-8000-000000000001",i+1),
                String.format(Locale.ROOT,"%08x-0000-4000-8000-000000000002",i+1),1,
                "00000000-0000-4000-8000-000000000003",(i%25+0.5)/25.0,(i/25+0.5)/4.0,
                0,"branching_tree",hex.toString(),arrayOf("SEED","SPROUT","YOUNG")[i%3],i+1L,
            ))
        }
        activity.setContent { NativeForest(nodes,Collections.emptyMap(),Modifier.fillMaxSize()) }
    }
}

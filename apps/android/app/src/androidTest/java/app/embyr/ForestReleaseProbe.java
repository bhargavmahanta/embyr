package app.embyr;

import android.app.Activity;
import android.view.View;
import androidx.compose.ui.Modifier;
import androidx.compose.runtime.Composer;
import androidx.compose.ui.platform.ComposeView;
import app.embyr.core.model.WorldNodeDto;
import app.embyr.feature.world.ForestCanvasKt;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Locale;
import kotlin.Unit;
import kotlin.jvm.functions.Function2;

/** Test APK only: Java composition bridge, production renderer, no persistence or API. */
public final class ForestReleaseProbe {
    private ForestReleaseProbe() {}
    public static void present(MainActivity activity) {
        try {
            ArrayList<WorldNodeDto> nodes = new ArrayList<>(100);
            for (int i = 0; i < 100; i++) {
                byte[] bytes = MessageDigest.getInstance("SHA-256").digest(("m705-synthetic-" + i).getBytes(StandardCharsets.UTF_8));
                StringBuilder seed = new StringBuilder();
                for (byte value : bytes) seed.append(String.format(Locale.ROOT, "%02x", value & 255));
                nodes.add(new WorldNodeDto(
                    String.format(Locale.ROOT, "%08x-0000-4000-8000-000000000001", i + 1),
                    String.format(Locale.ROOT, "%08x-0000-4000-8000-000000000002", i + 1), 1L,
                    "00000000-0000-4000-8000-000000000003", (i % 25 + 0.5) / 25.0,
                    (i / 25 + 0.5) / 4.0, 0, "branching_tree", seed.toString(),
                    new String[] { "SEED", "SPROUT", "YOUNG" }[i % 3], i + 1L));
            }
            // R8 narrows this constructor's Context parameter to MainActivity.
            // Select the single compatible one-argument constructor rather than
            // retaining removed Context/default bridges in the application.
            Constructor<?> match = null;
            for (Constructor<?> constructor : ComposeView.class.getDeclaredConstructors()) {
                Class<?>[] parameters = constructor.getParameterTypes();
                if (parameters.length == 1 && parameters[0].isInstance(activity)) {
                    if (match != null) throw new AssertionError("Ambiguous ComposeView constructor");
                    match = constructor;
                }
            }
            if (match == null) throw new AssertionError("No compatible ComposeView constructor");
            match.setAccessible(true);
            ComposeView view = (ComposeView) match.newInstance(activity);
            Function2<Composer, Integer, Unit> header = (composer, flags) -> Unit.INSTANCE;
            Function2<Composer, Integer, Unit> content = (composer, flags) -> {
                ForestCanvasKt.NativeForest(nodes, Collections.emptyMap(), Modifier.Companion,
                    true, header, composer, 0, 0);
                return Unit.INSTANCE;
            };
            view.setContent(content);
            activity.setContentView(view);
        } catch (ReflectiveOperationException | java.security.NoSuchAlgorithmException failure) {
            throw new AssertionError("Production forest bridge failed", failure);
        }
    }
}

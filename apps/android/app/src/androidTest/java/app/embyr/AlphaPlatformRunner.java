package app.embyr;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;

/** Framework-only release feasibility probe. No shared Kotlin/AndroidX test bootstrap ABI. */
public final class AlphaPlatformRunner extends Instrumentation {
    private static final String CLASS = "app.embyr.AlphaPlatformRunner";
    private static final String TEST = "nonDebuggableAlphaLauncherCanBeInstrumented";

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        // A bounded smoke probe is the only supported operation.
        if (arguments == null || !CLASS.equals(arguments.getString("class"))) {
            Bundle result = new Bundle();
            result.putString("shortMsg", "Unsupported Alpha probe selection");
            finish(Activity.RESULT_CANCELED, result);
            return;
        }
        start();
    }

    private Bundle status() {
        Bundle status = new Bundle();
        status.putString("class", CLASS);
        status.putString("test", TEST);
        status.putInt("numtests", 1);
        status.putInt("current", 1);
        return status;
    }

    @Override public void onStart() {
        Activity activity = null;
        sendStatus(1, status());
        try {
            if (!"app.embyr.alpha".equals(getTargetContext().getPackageName())) {
                throw new AssertionError("Wrong target package");
            }
            if ((getTargetContext().getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
                throw new AssertionError("Release target is debuggable");
            }
            Intent intent = new Intent(Intent.ACTION_MAIN)
                .setClassName("app.embyr.alpha", "app.embyr.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = startActivitySync(intent);
            waitForIdleSync();
            final Activity launched = activity;
            runOnMainSync(() -> {
                if (launched.isFinishing() || !"app.embyr.alpha".equals(launched.getPackageName())) {
                    throw new AssertionError("Alpha launcher did not remain active");
                }
            });
            sendStatus(0, status());
            Bundle result = new Bundle();
            result.putString("stream", "Framework Alpha release smoke: one check passed; no JUnit/live-alpha/performance claim.");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            Bundle failed = status();
            failed.putString("stack", failure.getClass().getName());
            sendStatus(-2, failed);
            Bundle result = new Bundle();
            result.putString("shortMsg", "Alpha framework release probe failed");
            finish(Activity.RESULT_CANCELED, result);
        } finally {
            if (activity != null) {
                final Activity opened = activity;
                runOnMainSync(opened::finish);
            }
        }
    }
}

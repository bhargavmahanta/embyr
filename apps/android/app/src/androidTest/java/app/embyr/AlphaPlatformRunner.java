package app.embyr;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Bundle;
import android.util.Base64;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.json.JSONArray;
import org.json.JSONObject;

/** Framework-only release feasibility probe. No shared Kotlin/AndroidX test bootstrap ABI. */
public final class AlphaPlatformRunner extends Instrumentation {
    private static final String CLASS = "app.embyr.AlphaPlatformRunner";
    private static final String TEST = "nonDebuggableAlphaLauncherCanBeInstrumented";
    private boolean storage;
    private String owner;

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        // Only bounded launch or read-only storage probes are supported.
        if (arguments == null || !CLASS.equals(arguments.getString("class"))) {
            Bundle result = new Bundle();
            result.putString("shortMsg", "Unsupported Alpha probe selection");
            finish(Activity.RESULT_CANCELED, result);
            return;
        }
        String operation = arguments.getString("operation", "launch");
        storage = "storage".equals(operation);
        owner = arguments.getString("owner", "");
        if ((!storage && !"launch".equals(operation)) || (storage &&
            !owner.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))) {
            Bundle result = new Bundle();
            result.putString("shortMsg", "Unsupported Alpha probe arguments");
            finish(Activity.RESULT_CANCELED, result);
            return;
        }
        start();
    }

    private Bundle status() {
        Bundle status = new Bundle();
        status.putString("class", CLASS);
        status.putString("test", storage ? "readonlyOwnerStorageCanBeInspected" : TEST);
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
            if (storage) {
                JSONObject observation = inspectStorage();
                if (observation.toString().length() > 400_000) {
                    throw new AssertionError("Storage evidence exceeds bounded result size");
                }
                sendStatus(0, status());
                Bundle result = new Bundle();
                result.putString("m706_storage", observation.toString());
                result.putString("stream", "Framework read-only owner storage probe; no mutation or JUnit claim.");
                finish(Activity.RESULT_OK, result);
                return;
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

    private JSONObject inspectStorage() throws Exception {
        File file = getTargetContext().getDatabasePath("embyr-private.db");
        if (!file.isFile()) throw new AssertionError("Existing Alpha database required");
        JSONObject result = new JSONObject();
        result.put("package", getTargetContext().getPackageName());
        result.put("owner", owner);
        result.put("read_only", true);
        try (SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getPath(), null,
                SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS)) {
            if (!db.isReadOnly() || db.getVersion() != 4) throw new AssertionError("Readonly Room4 required");
            result.put("room_version", db.getVersion());
            // A deferred read transaction holds one consistent WAL snapshot.
            db.execSQL("BEGIN DEFERRED TRANSACTION");
            try {
                result.put("commands", rows(db, "SELECT * FROM commands WHERE ownerId=? ORDER BY createdAtEpochMs,id LIMIT 2001"));
                result.put("world_meta", rows(db, "SELECT * FROM world_meta WHERE ownerId=?"));
                result.put("world_nodes", rows(db, "SELECT * FROM world_nodes WHERE ownerId=? ORDER BY objectId LIMIT 2001"));
                result.put("world_regions", rows(db, "SELECT * FROM world_regions WHERE ownerId=? ORDER BY objectId LIMIT 2001"));
                result.put("journey", rows(db, "SELECT * FROM journey_state WHERE ownerId=?"));
            } finally {
                db.execSQL("ROLLBACK");
            }
        }
        JSONObject stores = new JSONObject();
        for (String name : new String[] { "auth-session.bin", "auth-code-verifier.bin" }) {
            File store = new File(getTargetContext().getNoBackupFilesDir(), name);
            if (store.isFile()) {
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(store.toPath()));
                StringBuilder hex = new StringBuilder();
                for (byte value : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
                stores.put(name, hex.toString());
            }
        }
        // Only encrypted-store hashes are returned; no tokens or key material.
        result.put("encrypted_store_sha256", stores);
        return result;
    }

    private JSONArray rows(SQLiteDatabase db, String sql) throws Exception {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.rawQuery(sql, new String[] { owner })) {
            while (cursor.moveToNext()) {
                JSONObject row = new JSONObject();
                for (int index = 0; index < cursor.getColumnCount(); index++) {
                    String name = cursor.getColumnName(index);
                    switch (cursor.getType(index)) {
                        case Cursor.FIELD_TYPE_NULL: row.put(name, JSONObject.NULL); break;
                        case Cursor.FIELD_TYPE_INTEGER: row.put(name, cursor.getLong(index)); break;
                        case Cursor.FIELD_TYPE_FLOAT: row.put(name, cursor.getDouble(index)); break;
                        case Cursor.FIELD_TYPE_BLOB:
                            row.put(name, new JSONObject().put("base64", Base64.encodeToString(cursor.getBlob(index), Base64.NO_WRAP)));
                            break;
                        default: row.put(name, cursor.getString(index));
                    }
                }
                result.put(row);
                if (result.length() > 2000) throw new AssertionError("Truncated storage evidence is not allowed");
            }
        }
        return result;
    }
}

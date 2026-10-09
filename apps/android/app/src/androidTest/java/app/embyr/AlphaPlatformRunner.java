package app.embyr;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteCursor;
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
    private boolean forest;
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
        forest = "forest".equals(operation);
        owner = arguments.getString("owner", "");
        if ((!storage && !forest && !"launch".equals(operation)) || (storage &&
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
        status.putString("test", storage ? "readonlyOwnerStorageCanBeInspected" : (forest ? "productionForestCanBePresented" : TEST));
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
            if (forest) {
                final Activity foreground = activity;
                runOnMainSync(() -> ForestReleaseProbe.present((MainActivity) foreground));
                waitForIdleSync();
                try { Thread.sleep(2000); } catch (InterruptedException e) { throw new AssertionError(e); }
            }
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
            // Android intercepts BEGIN as an exclusive transaction. Use one
            // compound SELECT and require its complete result in one cursor window.
            JSONObject snapshot = readSnapshot(db);
            for (String table : new String[] { "commands", "world_meta", "world_nodes", "world_regions", "journey_state" }) {
                result.put(table.equals("journey_state") ? "journey" : table, snapshot.getJSONArray(table));
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

    private JSONObject readSnapshot(SQLiteDatabase db) throws Exception {
        String[] tables = { "commands", "world_meta", "world_nodes", "world_regions", "journey_state" };
        String[] keys = { "id", "ownerId", "objectId", "objectId", "ownerId" };
        java.util.ArrayList<String> terms = new java.util.ArrayList<>();
        java.util.ArrayList<String> bindings = new java.util.ArrayList<>();
        for (int table = 0; table < tables.length; table++) {
            try (Cursor schema = db.rawQuery("PRAGMA table_info(\"" + tables[table] + "\")", null)) {
                int index = schema.getColumnIndexOrThrow("name");
                while (schema.moveToNext()) {
                    String column = schema.getString(index);
                    if (!column.matches("[A-Za-z0-9_]+")) throw new AssertionError("Unexpected schema column");
                    terms.add("SELECT '" + tables[table] + "' AS kind, \"" + keys[table] + "\" AS row_key, '" + column +
                        "' AS field, \"" + column + "\" AS value FROM (SELECT * FROM \"" + tables[table] +
                        "\" WHERE ownerId=? LIMIT 2001)");
                    bindings.add(owner);
                }
            }
        }
        if (terms.isEmpty() || terms.size() > 100) throw new AssertionError("Unexpected Room4 schema");
        String sql = String.join(" UNION ALL ", terms) + " ORDER BY 1,2,3";
        java.util.Map<String, java.util.Map<String, JSONObject>> grouped = new java.util.LinkedHashMap<>();
        for (String table : tables) grouped.put(table, new java.util.LinkedHashMap<>());
        try (Cursor cursor = db.rawQuery(sql, bindings.toArray(new String[0]))) {
            boolean hasRow = cursor.moveToFirst();
            if (!(cursor instanceof SQLiteCursor)) throw new AssertionError("Native SQLite cursor required");
            android.database.CursorWindow window = ((SQLiteCursor) cursor).getWindow();
            if (hasRow && (window == null || window.getStartPosition() != 0 || window.getNumRows() != cursor.getCount())) {
                throw new AssertionError("Snapshot would require cursor-window re-execution");
            }
            if (hasRow) do {
                String kind = cursor.getString(0), key = cursor.getString(1), field = cursor.getString(2);
                java.util.Map<String, JSONObject> rows = grouped.get(kind);
                if (rows == null) throw new AssertionError("Unexpected table kind");
                JSONObject row = rows.get(key);
                if (row == null) { row = new JSONObject(); rows.put(key, row); }
                if (rows.size() > 2000) throw new AssertionError("Truncated storage evidence is not allowed");
                switch (cursor.getType(3)) {
                    case Cursor.FIELD_TYPE_NULL: row.put(field, JSONObject.NULL); break;
                    case Cursor.FIELD_TYPE_INTEGER: row.put(field, cursor.getLong(3)); break;
                    case Cursor.FIELD_TYPE_FLOAT: row.put(field, cursor.getDouble(3)); break;
                    case Cursor.FIELD_TYPE_BLOB:
                        row.put(field, new JSONObject().put("base64", Base64.encodeToString(cursor.getBlob(3), Base64.NO_WRAP)));
                        break;
                    default: row.put(field, cursor.getString(3));
                }
            } while (cursor.moveToNext());
        }
        JSONObject result = new JSONObject();
        for (String table : tables) result.put(table, new JSONArray(grouped.get(table).values()));
        return result;
    }
}

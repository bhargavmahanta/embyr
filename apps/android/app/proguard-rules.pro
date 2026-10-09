# Add only rules required by a proven release build failure.

# Same-signature AndroidJUnitRunner failed before test discovery with
# NoClassDefFoundError: androidx.tracing.Trace. The test APK shares this
# production dependency; preserve only this third-party instrumentation ABI.
# Do not retain application classes or disable optimization for profiling.
-keep class androidx.tracing.Trace { public static *; }

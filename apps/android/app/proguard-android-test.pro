# AndroidX Test references these compile-time Error Prone annotations without
# packaging them. R8 reported exactly these two missing types in release tests.
# This file applies only to instrumentation; it does not retain application code.
-dontwarn com.google.errorprone.annotations.CanIgnoreReturnValue
-dontwarn com.google.errorprone.annotations.MustBeClosed

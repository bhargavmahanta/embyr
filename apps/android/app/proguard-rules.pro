# The signed test APK invokes this existing production renderer entry directly.
# Release probe DEX inspection proved R8 removed its callable JVM entry.
# Keep only this method and descriptor identities; other application code remains optimized.
-keep,allowoptimization,includedescriptorclasses class app.embyr.feature.world.ForestCanvasKt {
    public static void NativeForest(java.util.List,java.util.Map,androidx.compose.ui.Modifier,boolean,kotlin.jvm.functions.Function2,androidx.compose.runtime.Composer,int,int);
}

package app.embyr;

/** Test-only screen-coordinate path. One epoch spans warmup, reset and measurement. */
public final class ForestMotionPath {
    private ForestMotionPath() {}
    private static double seconds(long elapsed) {
        if (elapsed < 0) throw new IllegalArgumentException("Negative motion epoch");
        return elapsed / 1e9;
    }
    public static float radius(long elapsed) {
        return (float) (52 - 16 * Math.cos(2 * Math.PI * seconds(elapsed) / 5));
    }
    public static float x(long elapsed) { return (float) (55 * Math.sin(seconds(elapsed) * .7)); }
    public static float y(long elapsed) { return (float) (38 * Math.cos(seconds(elapsed) * .9)); }
    public static boolean expanding(long elapsed) {
        seconds(elapsed);
        return elapsed % 5_000_000_000L < 2_500_000_000L;
    }
}

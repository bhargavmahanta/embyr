# M7-06 physical release performance gate

Protocol approved during planning before measurements. Collector, extractor and scene source hashes must receive independent review and be frozen before baseline collection. No M7-06 results have been produced yet.

## Comparable setup

Use the actual signed, minified, non-debuggable, shell-profileable `app.embyr.alpha` APK on the serial-explicit physical Samsung SM-M127G/API33, at 60Hz ±0.5Hz. First prove that same-signature instrumentation can exercise this release without broad R8 keep rules. Synthetic scenes belong only to that harness and render production `NativeForest` with its 320dp viewport; never persist them in Room or the backend. Preserve the deterministic M7-05 scene generator and record its hash.

Record APK/source/tree/build inputs, certificate, power/charging, brightness, compilation, thermal state and actual pre-run accessibility/settings. Profile at font scale 1.0, animator scale 1.0 and TalkBack off; restore the captured settings afterward. Keep these conditions comparable between baseline and final runs. Thermal status no greater than LIGHT is a start precondition; allow at most two five-minute cooling retries before a run, recording every attempt. Heating during a valid run never permits discarding it.

Use digest-verified official tools:

| Tool | Official asset SHA-256 |
|---|---|
| Perfetto v58.2 Linux amd64 ZIP | `32c739f71b2d39721afd294c0b038f2499a44a71b5b6bcdd85b83faca0b240b9` |
| bundletool 1.18.3 JAR | `a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29` |

## Workload and populations

Run `(real alpha, 100 synthetic nodes, 500 synthetic nodes) × 3`, in that order, before and after renderer changes. Each run warms up for five seconds and measures twenty seconds of continuous pan/zoom. Reset at measured second 5 and select at 10. Synthetic authoritative growth is at 15 and a correction at 17; genuine public learner action → worker growth is a separate live gate. Keep all nodes, coordinates, seeds, pins and semantic states.

Include transitions and first-draw frames occurring in the measurement window. Require at least 100 complete samples **per population**, zero lost samples, positive timestamps/deadlines and trustworthy surface associations. Missing metrics, incomplete populations or unreliable association produce NOT RUN, never PASS. Use raw nanoseconds and nearest-rank percentiles, without rounding before comparison. Retain traces and raw paired FrameMetrics samples.

CPU-side duration is pinned Perfetto `android_cpu_time_per_frame.cpu_time`: elapsed app frame-stage duration, including VSYNC delay, Choreographer and associated DrawFrame stages. It is not scheduled CPU execution time. Actual cadence uses deduplicated SurfaceFlinger presentations associated with the foreground app surface; app FrameTimeline slice duration is not presentation cadence. Record layer selection and app/display-token joins. FrameMetrics on API33 is an independent sample population; `TOTAL_DURATION >= DEADLINE`, for a positive allocated deadline, counts as a miss.

## Fixed thresholds

Every valid run must satisfy every threshold. All three runs per scene must pass; no selection of the best run or threshold changes after results.

| Metric | Maximum |
|---|---:|
| CPU-side duration p95 | 16,670,000ns |
| CPU-side duration p99 | 33,340,000ns |
| Actual presentation interval p95 | 18,340,000ns |
| Presentation intervals greater than 25,000,000ns | 1% of intervals |
| FrameTimeline positive overrun | 1% of complete frames |
| FrameMetrics allocated deadline misses | 1% of complete samples |
| Continuous-motion presentation gap | 100,000,000ns |

Discrete reset/selection must also work visibly. This protocol makes no input-latency claim. Historical synthetic debug measurements remain historical; zero allocated misses alone does not prove smoothness.

Definitions: [Perfetto frame metrics](https://perfetto.dev/docs/analysis/stdlib-docs#android-frames-per_frame_metrics), [FrameTimeline](https://perfetto.dev/docs/data-sources/frametimeline), [Android FrameMetrics](https://developer.android.com/reference/android/view/FrameMetrics).

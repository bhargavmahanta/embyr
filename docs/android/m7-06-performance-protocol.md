# M7-06 physical release performance gate

Protocol approved during planning before measurements. Collector, extractor, device profile and scene source hashes must receive independent review and be frozen before collection. The retained Samsung SM-M127G attempt is NOT RUN: seven required measured app frame ends were incomplete. Preserve its ledger, traces and reviews; it is not a complete baseline or a Samsung performance pass.

## Comparable setup

Use the actual signed, minified, non-debuggable, shell-profileable `app.embyr.alpha` APK on an explicitly reviewed physical device at 60Hz ±0.5Hz. The original Samsung SM-M127G/API33 remains unqualified. The operator supplied a Samsung SM-A376E/API36 for separate qualification; availability and suitable display settings alone do not qualify its measurement source. First prove that same-signature instrumentation can exercise this release without broad R8 keep rules. Synthetic scenes belong only to that harness and render production `NativeForest` with its 320dp viewport; never persist them in Room or the backend. Preserve the deterministic M7-05 scene generator and record its hash.

Record APK/source/tree/build inputs, certificate, power/charging, brightness, compilation, thermal state and actual pre-run accessibility/settings. Profile at font scale 1.0, animator scale 1.0 and TalkBack off; restore the captured settings afterward. Keep these conditions comparable between baseline and final runs. Thermal status no greater than LIGHT is a start precondition; allow at most two five-minute cooling retries before a run, recording every attempt. Heating during a valid run never permits discarding it.

Use digest-verified official tools:

| Tool | Official asset SHA-256 |
|---|---|
| Perfetto v58.2 Linux amd64 ZIP | `32c739f71b2d39721afd294c0b038f2499a44a71b5b6bcdd85b83faca0b240b9` |
| bundletool 1.18.3 JAR | `a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29` |

## Alternate-device qualification

Before a benchmark series, independently review the exact device profile, artifacts, collector, extractor, configuration and source-integrity checks. Keep separate device, qualification and benchmark ledgers. Inspect existing installations before installing; preserve unknown signing identities and account data. Reuse hash-verified artifacts when their inputs are unchanged.

Qualify with one bounded synthetic500 capture using the existing five-second warmup, twenty-second workload and at most45-second recorder duration. Establish coverage from raw eligible starts before filtering. Require complete app actual/expected endpoints, CPU-frame joins and unique named-SurfaceFlinger display-token/presentation associations. Validate integer timestamps, trusted service bounds and the MONOTONIC/BOOTTIME relationship covering both original windows. A periodic snapshot setting alone does not prove that bracketing clock observations exist. Missing, sentinel, unsupported-clock or ambiguous data remains NOT RUN; never reconstruct missing timestamps or discard incomplete frames.

Require at least100 complete samples in each independent population and zero loss. QUALIFIED establishes measurement-source reliability only; it is neither a baseline nor performance PASS. Retain threshold outcomes without using them to choose qualification attempts. Preserve all failures; any revised procedure or continuation needs independent review, with no automatic retry. Obtain independent qualification-evidence approval before the nine-case baseline, and repeat integrity checks in every case.

Collect baseline and optimized results on the same qualified device, OS, display and frozen scene inputs. A device or material collector change requires a reviewed new comparison and retained history. Do not compare devices as optimization evidence or claim that another device's results qualify the Samsung SM-M127G.

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

## Execution when a physical device is unavailable

Preserve each attempt ledger, raw trace, original analysis, cleanup receipt and independent review. An independently approved later analysis is a separate artifact; it does not overwrite the original NOT RUN result. Device-source qualification establishes measurement reliability and is separate from both a comparable baseline and final performance acceptance.

A first baseline case that fails source integrity stops the ordered series. Do not advance its ledger from framework completion, matching sample counts or partial metrics. A positive lifetime tracing-service discard count without a before-window observation cannot be assigned to a session or measurement window; per-buffer zeros alone do not resolve it. Investigate retained evidence and review any proposed additional observations before another capture. Numerical thresholds remain unchanged.

When the phone is unavailable, continue release auditing, controlled-clock/JVM/schema checks, signing recovery, documentation and review. Physical accessibility, installation/upgrade, live journeys and the complete performance series remain pending. Renderer optimization requires the approved comparable baseline. Close neither the child issue nor the umbrella milestone from offline evidence alone.

The replacement test workload dispatches synthetic pointer events through the production Compose view on one main-thread Choreographer callback. It bypasses system input dispatch and makes no system-input or input-latency equivalence claim. Its main-thread dispatch cost remains measured. Preserve screen/raw and view-local coordinates, a continuous warmed-up gesture across reset and selection, and every callback/frame; acknowledgment polling must not pause motion. Record intended/actual callback timestamps, missed input ticks, routing and cancellation evidence. Routing alone does not prove camera movement. A delayed action or stationary interval remains in the full twenty-second measurement and its diagnostics; never abort merely to exclude slow frames. Independently qualify the exact replacement collector before starting a fresh comparable baseline.

An instrumentation-only lifecycle experiment may hold the target alive after the complete measurement, tail delivery, motion cancellation and FrameMetrics listener detachment. Register the ephemeral package-scoped receiver before collection; require the shell's DUMP permission and a one-shot 128-bit nonce. READY is a control status, never a framework pass. The host drains both status streams, observes the after-clock pair, stops or verifies automatic completion of its exact owned recorder, and retains and hashes the trace while the same target PID/start ticks remain alive. Only then send ACK; ACK means retention, even when later loss checks fail. Bound the holder to fifteen seconds and the recording to forty-five seconds. Prepare clock tooling outside the main recording; independent before/after observations must still bracket the original measurement. Keep heavy trace analysis outside the hold. Missing ACK, uncertain ownership or retention, and trace loss remain NOT RUN. Review the exact experiment and qualification evidence before any new benchmark series; preserve every prior attempt and threshold.

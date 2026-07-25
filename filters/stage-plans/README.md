# Profiler Stage Plans

These files are the human-authored feature-ownership boxes consumed by:

```powershell
target\release\fit-candidates.exe corner.tf.json corner.fit.json --stage-plan filters\stage-plans\NAME.profile-plan.json
```

They register lane identity; they are not measurements and must not be used to
invent a missing source TF. `source_evidence.status = ANALYTIC_ONLY_NO_MEASURED_TF`
means the acoustic profiler must refuse. That source belongs on the direct
physics-to-registered-lanes path instead.

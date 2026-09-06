# Lab doctor

Get a dated, plain-language report of this isolated lab's services, storage and
recovery evidence. The command only reads observations. It never starts the VM,
restarts a service, updates software, removes data, logs in or calls a model.

From the repository root, with the existing prepared environment and isolated
lab already running:

```sh
.runtime/venv/bin/python integrations/stackarr/doctor.py \
  --docker-host unix:///absolute/path/to/.colima/lab/docker.sock \
  --engine-id YOUR_VERIFIED_LAB_ENGINE_ID
```

The socket and engine ID come from the existing isolated setup, not another
machine. An unavailable or mismatched lab produces an unknown report and no
service probes. No production socket or client deployment is supported here.
The doctor does not authorize resuming a VM; the operator owns that decision.

Add `--details` for every explanation, or `--json` for structured output. Output
contains fixed friendly service labels and measurements, not Docker labels,
container IDs, IP addresses, host paths, secrets or raw command errors. Runtime
error details are deliberately not echoed into a shareable report. A report is
generated on demand; it is not continuous monitoring or a complete security audit.

## Reading the results

- **Running:** the supported service-manager container is running. This does not
  establish working agent conversations or management actions.
- **Responding:** Jellyfin's basic public health and initialization checks answer.
  Sign-in, playback and private records are not checked. HTTP redirects/proxies are
  disabled, and the container must have the expected loopback port and pinned image.
- **Stopped:** Docker actually reports the service stopped. It may be intentional;
  ask its operator. A running but unready endpoint is **unavailable**.
- **Unknown:** access, isolation, identity or a measurement could not be verified.
  This is not a green result and does not prove a failure's cause.
- **Low storage:** either checked guest filesystem is at least 90% used or has less
  than 1 GiB available. These are simple trial warning thresholds. Nothing is deleted.
  The checks cover guest system/service storage, not the physical Mac disk, disk
  reliability, removable media, every mount or space reservation by other software.

## Backup evidence is separate from current protection

Without supplied evidence, backup protection is unknown. Optionally point to a
retained successful integration-run result **under this repository's `.runtime/`**:

```sh
# Append to the doctor command above:
--backup-evidence .runtime/acceptance-RUN_TIMESTAMP/result.json
```

The doctor checks the record's engine/image scope, successful recovery checks,
completion date and SHA-256 of its two retained archives. It refuses absent,
mismatched, malformed or future-dated proof. It reads only the result and the
fixed adjacent archive names; it does not extract or publish their contents.

Matching evidence is **recorded**, or **stale** after 24 hours. That age threshold
is a disclosed trial policy, not a recovery guarantee. Even recent matching evidence
only documents the previous sample-library test. It does not prove backups include
new changes, an independent off-machine copy or that current data can be recovered.
The record is local operator-supplied evidence, not a signed independent attestation.

## Validation boundary

Actual acceptance uses the existing guarded Ubuntu/Colima lab: stopped report,
running/reachable report, deliberately stopped media service, recovered service
readback, and restoration of the original stopped state. Doctor runs are compared
against independent container state/configuration/mount observations to check that
the report itself makes no changes. Test setup/stop/start are separate operator
actions using the existing scoped adapter, never actions inside the doctor.

Low-space, malformed storage, old/missing/tampered evidence and unavailable HTTP
edge cases use labelled deterministic fixtures. Disks are never filled for testing.
Run the full integration regression suite with:

```sh
PYTHONPATH=integrations/stackarr .runtime/venv/bin/python -m unittest discover -s integrations/stackarr/tests -v
```

The prior integration and data remain unchanged. Rollback is to the previously
accepted `ea984c5d427b5dd8f3990301551e41e3333d2df8` code; the report has no scheduled
process to stop and makes no persistent application changes.

### Recorded result — 6 September 2026

Actual existing-lab acceptance completed at 12:15 UTC: stopped → responding →
deliberately stopped → responding again. Four report runs preserved container
state, configuration and mounts; mount comparison normalizes Docker's unordered
list. Both services were returned to their original stopped state, and prior
recovery archive hashes still match. Guest system/service storage were measured
without altering disk usage. Missing evidence was also reported unknown in a
real CLI run. No private application records or login were used.

The integration suite passed 23 tests (the prior 17 plus six doctor tests); all
12 onboarding tests also passed. Fixture backup files are deliberately labelled
test bytes, not claimed as successful application recovery. The real recovery
record comes from the previously accepted integration and its retained archives.

# Lab doctor

Get a dated, plain-language report of this isolated lab's services, storage and
recovery evidence. The command only reads observations. It never starts the VM,
restarts a service, updates software, removes data, logs in or calls a model.

From the repository root, run:

```sh
./check-my-lab
```

For more explanation, use `./check-my-lab --details`. Structured output is
available with `./check-my-lab --json`. No socket, engine ID, login or model is
needed. You can also invoke the script by its absolute path from another folder.

This shortcut supports the existing reviewed local reference, **not automatic
setup of a newly cloned project or discovery of another lab**. It uses the exact
PR1 acceptance record already retained under `.runtime/`. Its integrity hash is
anchored in the code; the engine identity is read from that record, not copied
into a second editable configuration. The socket path comes from the existing
isolation guard. If the optional provisioner's `engine.json` exists, it must agree
with the accepted reference. No new enrollment file is created.

Missing, altered, linked, malformed or contradictory saved setup stops the command
with understandable guidance before the doctor is called. Restoring/replacing a
reference is an operator review, not a prompt to adopt whatever Docker engine is
currently discoverable. A missing Python environment produces a short preparation
message; the script does not install dependencies. A missing dependency likewise
produces a short incomplete-tools message rather than an internal traceback.

With a valid saved reference but a suspended/unreachable/mismatched lab, the same
doctor reports unknown and performs no service probes after its guard fails.
Nothing starts the VM or its services. Exit code 2 means setup/lab verification is
unavailable; exit code 0 means the report was collected, **not** that all services
or backups are healthy. Stopped services remain visibly stopped in a collected report.

Output contains fixed friendly service labels and measurements, not Docker labels,
container IDs, IP addresses, host paths, secrets or raw command errors. Reports
remain snapshots rather than continuous monitoring or a complete security audit.

### Advanced operator invocation

The original doctor remains available, using the same checker and guard:

```sh
.runtime/venv/bin/python integrations/stackarr/doctor.py \
  --docker-host unix:///absolute/path/to/.colima/lab/docker.sock \
  --engine-id YOUR_VERIFIED_LAB_ENGINE_ID
```

No production socket or client deployment is supported here. The operator owns
setup/VM decisions; explicit invocation does not authorize another deployment.

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

The shortcut supplies its already-reviewed reference to the same backup checker.
With advanced invocation and no supplied evidence, backup protection is unknown.
An operator can optionally point to a
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
accepted doctor baseline `61e6ec2d015919c136bee6c70b34cc73cf84794d` code; the report has no scheduled
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

### Shortcut validation — 6 September 2026

`./check-my-lab` and its JSON mode ran against the same retained lab at12:35 UTC,
without connection arguments, including invocation from a different working
directory. Both correctly showed the stopped services and measured storage.
Independent before/after comparisons confirmed unchanged service state/configuration/
mounts and unchanged reference bytes; no new setup file was created. The initial
suspended invocation correctly reported unknown without starting the lab.

The integration suite passes31 tests (the prior23 plus8 shortcut tests), alongside
12 onboarding tests. Invalid setup and missing dependencies use labelled fixtures;
no real saved setup was edited. The accepted doctor/guard remain the checker.

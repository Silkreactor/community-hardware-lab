# Isolated Stackarr / Hermes / Jellyfin integration

This is an executable integration acceptance journey, not a ready-to-install
community appliance. It runs the actual Stackarr MCP server, calls the actual
Hermes elicitation handler and consent router, operates an actual Jellyfin
container, and recovers its application database and original sample media into
new volumes and a separate container. No model provider or API credit is used.

## What the boundary proves

- Stackarr observes the dedicated engine and restarts only the trial target.
- Observe/manage profiles, baseline Hermes's empty approval, decline, session,
  permanent, cancel, timeout, absent elicitation and an overlong form cannot restart it.
- Repaired Hermes translates one exact current-action approval into `approve:true`.
  The existing reviewed patch and bridge are reused byte-for-byte; no new consent
  implementation replaces them. External UI/config/session helpers are stand-ins.
- Restart must change Docker's start timestamp and preserve authenticated app use.
- A stopped-service backup restores actual users, library records, a favourite and
  media bytes. Recovery volumes differ from the original. Returning to the original
  is tested; originals and recovery evidence are preserved.

The deterministic test surface supplies the approval decisions. This does **not**
prove human, Telegram, full Hermes startup, conversational-agent or model acceptance.
Recovery uses this harness's explicit consistent-volume archive workflow; it is
**not** a claim that Stackarr's native backup workflow covers this installation.
Neither an archive filename check nor a container health icon proves recovery.

## Pins and provenance

| Component | Immutable pin |
| --- | --- |
| Stackarr alpha.19 source | `91100909f3b87afe27afbbe0348e8456701560eb` |
| Stackarr release image | `polyphonic/stackarr@sha256:def56c90a322a7eda3faa2e13a00596673bf9c0ed77a2190283d01fa23536b28` |
| Hermes source | `5fc308a70719a83cccdbba4c0e39c23f5a8239d5` |
| Jellyfin 10.11.8 image | `jellyfin/jellyfin@sha256:1694ff069f0c9dafb283c36765175606866769f5d72f2ed56b6a0f1be922fc37` |
| Reused consent patch SHA-256 | `028c8b252c7d0f0496dc5d6968557fab6b4d7fd3eabe1099440f340e2b2aa7a6` |
| Reused consent bridge SHA-256 | `30ad5b433994fab08122ef7f70cbdf21f97c9a31057df2199ede9b4d7439c4b3` |

Hermes is MIT licensed; [its notice](compat/HERMES-LICENSE) accompanies the patch's
upstream context. Stackarr retains GPL-3.0-only; Jellyfin retains its upstream
GPL licence. Downloaded runtimes are ignored and are not republished here. Source
and image pins are deliberate test baselines, not claims of latest releases.

## Prepare the runtime

Developer prerequisites: macOS ARM64, already installed Colima, Docker CLI, Git,
Python 3.12, enough free disk and about 3 GiB available for the disposable VM.
The root onboarding module remains independent of these dependencies.

From the repository root, acquire public sources and wheel-only dependencies:

```sh
python3.12 integrations/stackarr/prepare_sources.py
```

The script verifies exact patch/bridge/module hashes and source commits. It
refuses unexpected changes. Python dependencies are version-pinned; wheel
artifact hashes are not yet locked. Nothing starts an AI provider.

Create a **new** Colima profile named `lab` only if that name is unused. Do not
reuse another installation or attach its socket. The first verified run used:

```sh
colima start lab --cpu 2 --memory 3 --disk 16 --root-disk 16 \
  --mount none --ssh-agent=false --ssh-config=false --activate=false \
  --template=false --vm-type vz --network-address=false
```

Use the actual socket reported by Colima. This installation placed it at
`~/.colima/lab/docker.sock`; setting `COLIMA_HOME` did not relocate it. Inspect
the generated Lima configuration: no host-directory mounts, no agent forwarding,
no network address, and no default Docker-context activation. All subsequent
Docker commands must pass that explicit socket. The engine must be empty before
the trial's original resources are created. Stop if any of those checks fail.

Provision the two containers using [provision.py](provision.py), which verifies
the empty dedicated engine, creates only labelled trial resources, discovers its
socket group, and never publishes a non-loopback port:

```sh
python3 integrations/stackarr/provision.py --docker-host unix:///absolute/path/to/.colima/lab/docker.sock
```

It reports the engine ID. Use that exact ID for the actual journey:

```sh
python3 integrations/stackarr/acceptance.py \
  --docker-host unix:///absolute/path/to/.colima/lab/docker.sock \
  --engine-id THE_REPORTED_ENGINE_ID --run-disposable-trial
```

The client uses `admin` with only the `containers` group because Stackarr's
`manage` profile cannot restart containers. The dedicated engine is the real
security boundary: a Docker socket grants control of its entire VM, regardless
of the MCP profile. Never substitute a production socket. No private mounts,
production data, mesh, hardware devices or external model credentials belong here.

## Result, rollback and limits

Local evidence, archives and disposable login secrets stay under ignored
`.runtime/`; do not publish that directory. The JSON result records real
responses, decisions, timestamps, image pins, checks and archive hashes. Generated
sample sound is original and contains no private material. The login password
and archives use restricted permissions. Earlier failed attempts remain available.

On success, the original library runs at `http://127.0.0.1:18096`; its recovery
instance is stopped with volumes retained. Returning to the original does not
require restoring over it. Stop the entire trial with `colima stop lab`; this
preserves disks and data. No prune or automatic deletion is included.

The reference execution is an Ubuntu VM on macOS, not physical Ubuntu hardware
or a supported macOS Jellyfin deployment. Jellyfin's upstream documentation warns
that Docker-on-macOS is unsupported. No GPU transcoding, version upgrade/downgrade,
power-loss recovery, independent off-machine backup, farmOS/NOMAD integration or
offline deployment is claimed. Outbound public dependency downloads are required;
the test does not claim a firewall-enforced air gap. UI acceptance is separate from
the API/protocol journey.

Primary sources: [Stackarr source](https://github.com/polyphonic/stackarr/tree/91100909f3b87afe27afbbe0348e8456701560eb),
[Hermes source](https://github.com/NousResearch/hermes-agent/tree/5fc308a70719a83cccdbba4c0e39c23f5a8239d5),
[Jellyfin container guidance](https://jellyfin.org/docs/general/installation/container/).

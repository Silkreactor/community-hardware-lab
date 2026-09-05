# First isolated integration result — 2026-09-05

**22 actual journey checks passed**, 19:17:54–19:18:36 UTC. Separately, all 12
onboarding unit tests pass. Additional final mount/port/privilege preflight passed
against the actual engine, and provisioning correctly refused the nonempty engine
without mutation. Source preparation reran successfully with the exact reviewed
patch and bridge hashes. No full fresh provisioner rerun is claimed: initial
provisioning used the equivalent explicit commands now captured in that script.

The reference environment was an isolated Ubuntu 24.04.4 LTS ARM64 Colima guest on
macOS, Docker 29.5.2, two CPUs and 3 GiB assigned memory. Its dedicated Docker
engine began empty. No host-directory mounts or SSH-agent forwarding were enabled;
the existing default VM stayed stopped and the default Docker context stayed selected.
See [immutable runtime pins](../integrations/stackarr/README.md#pins-and-provenance).

## Observed results

| Journey | Actual result |
| --- | --- |
| Observe | Stackarr saw both real running containers and the dedicated volumes. |
| Refuse | Ten cases left the original start timestamp unchanged and service running: observe, manage, baseline empty approval, decline, session, permanent, cancel, timeout, no elicitation, overlong form. |
| Operate | Exact once-only repaired Hermes approval let Stackarr restart the named trial container; Docker independently reported a new start time. |
| Read back | Authenticated Jellyfin still returned the saved favourite. |
| Recover | After a clean stop, archived configuration/database and media were restored into fresh separate volumes; a second Jellyfin instance authenticated the original account and returned the same library item ID and favourite. |
| Verify media | Recovered original sample WAV bytes had the same SHA-256. |
| Roll back | Recovery instance stopped; original instance, account, library and favourite remained usable. No original was overwritten. |
| Browser | A separate supported-browser login to the original instance showed Community Reference and Community Bell in Favorites. Remember Me was unchecked. |

Archive SHA-256 values from the successful run (archives remain private/local):

- `config.tar`: `ec3560f624bcf5a01694751ac7386c42df1a77232c45a564b83ce57b440d18e8`
- `media.tar`: `e75694480d4694cae198e562f76aef83af75db1b798ca64e4c353fa3f701de3d`

## Findings and limits

Stackarr's `manage` profile does not permit container restart. The proof uses
`admin` with only its containers group, in a dedicated engine. Profiles do not
reduce the underlying Docker socket's authority over that VM. The named
`stackarr_restart_service` entry is a refusal placeholder in this baseline;
`stackarr_manage_container_resource` is the real operation used here.

The original Hermes response accepted the form without `approve:true`, so Stackarr
correctly refused it. The reused repair makes the exact current once-only response
work; it does not accept session or permanent grants. No unrestricted profile is used.

Three incomplete application runs exposed early-ready responses: basic public
status/health could return before authenticated routes were usable, and startup
metadata could omit the server ID. Those failures are retained locally. The final
runner waits for complete metadata and authenticated reads, and retries login only
on temporary HTTP 503, with a 60-second bound. Wrong credentials are not retried.

This is a working integration proof with deterministic test approvals and real
application data recovery. It is not full Hermes/model/human acceptance, a production
appliance, physical Ubuntu installation, version upgrade, power-loss test, off-machine
backup or hardware-accelerated media test. Jellyfin does not support Docker-on-macOS;
the VM result must not be sold as client Mac compatibility. FarmOS, NOMAD, mesh and
Knowledge Steward connectors are not implemented by this proof.

The owner kept one implementation lane for setup, source reuse, test failures and
fixes. Routine decisions required no intermediate handoffs; substantive security
and release review remains separate. No measured token-saving claim is made.

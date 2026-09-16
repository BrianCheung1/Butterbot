# Slice 1.0 release gate follow-up

**Verdict: FAIL. Slice 1.1 remains blocked.**

The four previously demonstrated code blockers are resolved in the current candidate; native
Linux acceptance evidence remains absent. No new runtime or schema changes were necessary in
this follow-up. Historical migrations 0001 and 0002 remain byte-identical to candidate 0003.

## Candidate and independent review

The source digest is `aa0d0bcf05fb8ebc48f6e5127b1ec439b02fee878e8e7212cdce5a36f83cb860`,
computed from the runner's sorted compact JSON path-to-SHA-256 map. Every source entry matches
`slice-1-0-candidate-0003.json`. The initial HEAD was
`15882168f1fe640ee667d196b3c588ea46f993b9`; it did not identify the dirty candidate.
The final commit and full byte-preserving transfer manifest are recorded in the generated
`.gate-local/candidate-binding.json`, alongside the Git bundle and source tar. This report and
the handoff are preparation records, not Linux evidence.

A separate reviewer inspected the remediation and ran its own focused verification; see
`slice-1-0-followup-independent.md`, its retained test log, and JUnit. The review closes B1-B4
at code level, subject to the native prerequisite. The initial working-tree changes include the
broader Slice 1.0 implementation and historical reviews; they are preserved in the candidate.
Historical policy simulations remain explicitly labeled diagnostic data and are not native proof.

## Verification observed in this follow-up

Commands used the repository Windows `.venv/Scripts` executables.

| Check | Observed result |
| --- | --- |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 90 files |
| `pyright` | 0 errors, 0 warnings, 0 informations |
| `python -m pytest -vv -ra -o faulthandler_timeout=60 --junitxml=.gate-local/local-junit.xml` | 554 passed, 32 skipped, 1 warning; 44.14 seconds |
| Fresh isolated `alembic upgrade head` | Passed through 0001, 0002, 0003 |
| `alembic check` on that database | Passed; no new upgrade operations |
| `git diff --check` | Passed; line-ending notices only |
| Source-manifest comparison | Exact match with candidate 0003 |

Raw local logs are `.gate-local/check-0.log` through `check-3.log`, `local-junit.xml`,
`results.json`, `migration-0.log`, `migration-1.log`, and `migration-results.json`.
No test failure or stall reproduced. The warning is the existing pytest-cache write denial.
The initial staged diff check found trailing blank lines in two historical probe scripts;
only those blank lines were removed. Original bytes and the failed check output are retained
under `.gate-local/original-*.txt` and `staged-diff-check-initial.log`.
The skips are 31 Linux-only cases and one Windows-denied symlink fixture; none establishes
native behavior. The independent focused run reports 198 passed, with the same cache warning.

## Blocking requirement

B5 remains open: no authorized native Linux SSH target/login or current evidence bundle was
provided or found in repository connection documentation or local SSH configuration. SSH tooling
exists locally, but that does not establish an available authorized host. No remote connection,
paid provisioning, native preflight, or native gate was attempted. Host kernel/distro, architecture,
mount/filesystem, identities, permissions, capabilities, mandatory native outcomes, and stability
of source during native execution therefore remain unverified.

Follow `slice-1-0-linux-handoff.md` on a provisioned host, retain the JSON and sibling raw artifacts,
and independently reconcile all 16 cases and exact final source identity. Any subsequent source
fix requires renewed appropriate local checks, candidate binding, and native execution.

## Non-blocking risks

- The previously reported intermittent stall is still unexplained; it did not recur here. Verbose
  logs and a 60-second faulthandler threshold were retained for diagnosis.
- Existing capacity evidence is development-host evidence. This task did not rerun the full
  capacity workload or satisfy production benchmark/backup/restore prerequisites.
- Dependency ranges are not a lock; capture and review actual Linux versions during execution.
- Outcome size/depth limits remain due before future input-derived persistent outcome payloads,
  as already recorded in decisions. Ping remains the only exposed command.

The necessary next input is the authorized provisioned Linux SSH target and login user, using
existing key/agent authentication. Passwords and private keys must not be sent in chat.

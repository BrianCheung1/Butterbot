# Slice 1.0 native Linux handoff

Status: prepared locally; native execution and acceptance are outstanding. Slice 1.1 is blocked.

The ignored `.gate-local/` directory contains `candidate.bundle`, `candidate-source.tar`, and
`candidate-binding.json`. The binding records the actual commit, working-tree state, all archived
file hashes, archive/bundle hashes, and the runner's deterministic source manifest. Transfer all
three together. They contain no virtual environment, local database, secrets, or caches.
Local check logs and historical simulated policy probes are not native acceptance evidence.

Clone the bundle into a new isolated checkout, check out the binding's commit, then overlay the
source tar there. The tar preserves the tested Windows working-file bytes, including line endings;
a plain Git checkout can change those bytes. Compare every archived file against the binding,
and compare `benchmarks.native_linux_gate._source_identity()` with `runner_source` before running.
Keep the checkout free of other Python source. Record `git status --short` even if line-ending
conversion makes the overlay appear dirty. HEAD alone does not identify the candidate.

Use an already authorized native Linux machine and Python 3.13. Create a fresh `.venv` with
`python3.13 -m venv .venv`, then install the reviewed project with `.venv/bin/python -m pip install
-e '.[dev]'`. Capture installed versions and rerun Ruff, formatting, Pyright, and the full pytest
suite on Linux; preserve failures and tracebacks. The local `dependencies.txt` is an observation,
not a cross-platform dependency lock. Do not install a copied Windows virtual environment.

Before the root-controlled gate, record `/etc/os-release`, `uname -a`, Python version,
`id`, `/proc/self/status` capabilities, `/proc/self/mountinfo`, `findmnt -T` and `df` for the parent,
and `setpriv --version` / `unshare --version`. Establish that the host is neither WSL nor an
ephemeral container. Check that the interpreter, source checkout, and dependency directories are
traversable/readable by the test service identity. Check UID 61001 and GIDs 61002/61003 for
collisions with real users/services before use; choose explicit isolated values if necessary.

Use `/var/lib/butterbot-native-gate` only as dedicated test storage, with administrator ownership
(default UID 0), service-nonwritable parent permissions, real local ext4/XFS, and at least both
5 GiB and 20% free. Inspect existing contents before any provisioning. Never use production data.
The controller must be root with the capabilities needed for ownership changes, identity changes,
and granting CAP_NET_RAW to the capability probe. `setpriv` and `unshare` must exist. The fixture
creates disposable administrator-owned/service-group `1770` roots and `0660` databases, and runs
service probes with a distinct nonroot UID/GID. The service and init network namespaces must match.

```bash
sudo .venv/bin/python benchmarks/native_linux_gate.py \
  --parent /var/lib/butterbot-native-gate \
  --report /tmp/butterbot-native-linux-report.json
```

Preserve the JSON and its entire sibling artifacts directory, plus the external preflight log.
Independently inspect raw JUnit, stdout/stderr, layout evidence, host identities and capabilities,
and before/after source manifests. Reconcile exactly 16 unique expected cases: seven layout,
five process-lock, and four SIGTERM cases (active, waiting, committing, fail-stop). Every mandatory
case must actually pass, including effective capabilities. Missing, duplicate, unexpected, failed,
errored, or improperly skipped cases fail acceptance. Only the exact namespace case and exact
documented pre-child util-linux EPERM/EACCES denial may skip. No source change during the run is
acceptable. Do not accept the runner's `passed` field without examining this underlying evidence.

After that review, update the release report with the exact commit/source binding and evidence
locations. PASS requires successful verification and complete valid native evidence. Until then
the release verdict remains FAIL, regardless of local Windows success.

# Handoff: Slice 1.7 policy design

Checkpoint prepared 2026-10-06. Read AGENTS.md, ROADMAP.md, docs/testing.md,
docs/decisions.md, docs/economy-design.md, docs/economy-simulation.md and the Slice 1.6
local/independent reports before work. Use the Git commit containing this handoff as the base.

## Accepted state

Phase 0 accepted; 1.0–1.3 implemented locally but native release acceptance deferred.
Slices 1.4 grants, 1.5 history/corrections and 1.6 daily have independent local PASS.
Daily is 15 coins per UTC calendar day, midnight reset, no streak/grace/catch-up.
Mandatory checks: Ruff/format/Pyright/diff passed; pytest 948 passed, 32 skipped, one known
Discord warning. Independent regression: 262 passed. Candidate source digest:
3512e2c639f4056f9150b131373f1d45852395220e92fc22b3ea29cd6cc10031.
Schema head: 20261005_0009. Prior migrations are frozen.

Tester reported daily working. Development launched as process 7856 with session
join-wb2fgkrf; verify current process state before any lifecycle action. Logs are ignored under
.gate-local/development-20261006-165110.*. Do not restart/migrate this session unnecessarily;
each launch creates a fresh database. No tokens or databases belong in Git.
Legacy global commands were cleared; 12 current commands remain in the test guild.

Preserve guild 152954629993398272, tester/operator 1047615361886982235 and channel
455431053528793098. Admin limits remain threshold100/per-operation1000/rolling24h10000;
alerts use local_log. Correction capabilities require explicit delegation. /give UX is deferred.

## Next authorized work

Begin Slice 1.7 policy design, not transfer implementation. Read existing transfer/anti-abuse
plans and propose concrete account-age/progression requirements, inbound/outbound rolling
limits, repeated-counterparty/funnel controls, freeze scope, review/alert thresholds and fee
choice. Explain dependencies on progression that does not yet exist; do not silently omit gates
or build progression early. Define durable business intent, confirmation/replay semantics and
atomic debit/credit/history/limit updates. Label numeric proposals unapproved and obtain user
policy approval before implementing them. Current single-user live scope must not be broadened
for P2P testing without authorization; offline tests can use synthetic players.

After implementation, follow the mandatory checks and independent adversarial/regression gate.
Do not start a dependent slice before local PASS. Phase 1 integration remains outstanding.
Linux production validation, deployment-host evidence, backups/restore and public-enable gates
remain deferred; Windows checks do not satisfy them. No production deployment is authorized.

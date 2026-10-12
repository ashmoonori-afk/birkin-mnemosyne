# Whole-product user journey audit and PR

## Contract and starting state

The user explicitly requests a second whole-product audit, implementation,
atomic commits and a pull request, including the earlier B1-B6 changes.
Tier: HEAVY, because this covers persistence, multiple clients and recovery.
The prior G001 evidence is retained; G002 in the ulw-loop ledger owns this work.

Working checkout: `C:/Users/lg/OmO Projects/bm-wt`.
Branch: `ulw/user-journey-gaps`.
Original base: `4b258d8`; refreshed origin/main: `08e518d` (labels, PR #80).
The previous work is not committed yet. Preserve it before integrating main.
No release, merge of the eventual PR, or history rewrite is authorized.

## Ideal user experience

1. A first-time MCP user can install a wheel, connect over stdio, remember
   and retrieve multilingual notes, and understand setup failures.
2. CLI and Python users address the same vault without surprising creation,
   overwrites, encoding damage, hidden ranking changes or missing metadata.
3. Returning agents receive complete, correctly scoped startup and handoff
   information; stale or broken required state cannot silently pass.
4. Edits, curation, imports, labels, archives and undo preserve information
   and reject stale/concurrent unsafe operations with actionable errors.
5. Existing vaults remain usable after upgrade, including Windows long paths.
6. Documentation and installed artifacts describe the actual released
   interfaces; all supported adapters retain the same contracts.

## Delegation and resource policy

Use small `quick` nodes on `opengateway/deepseek/deepseek-v4.1-flash-ultrafast`.
The existing quick routing was different; the explicit user request authorizes
the routing change. Verify the actual launch record, not a worker's claim.
Run at most one worker and one focused test process at a time on this PC.
No team: stages consume previous reports and do not require live debate.
Use a new workflow run per phase, with the lead synthesizing between phases.
No whole-suite run in workers.

## Ordered work

1. Inspect old changes, original QA evidence, repository rules and current main.
2. Verify routing through a bounded inventory task; record actual model.
3. Inventory every shipped module, adapter, example, package/build surface and
   relevant test file. Partition small audit units; record omissions explicitly.
4. Preserve verified B1-B6 changes as atomic commits with their direct tests.
5. Integrate current main without discarding labels or unrelated user changes.
6. Audit MCP setup and tool lifecycle; then independent CLI/Python use; then
   storage/recovery/hand-offs/labels; then adapters and packaging.
7. For every finding record file:line, current behavior, user impact, expected
   behavior, an exact reproduction and exact PASS/FAIL scenario. Distinguish
   hypotheses, confirmed defects, deliberate limits and environment failures.
8. Write `docs/product-audit.md` covering every inventory item and evidenced gap.
9. Implement each confirmed gap in a bounded unit with failing-before evidence,
   neighboring regression tests, real-surface QA and an atomic commit.
10. Keep English/Korean documentation and changelog aligned with actual behavior.
11. Run installed-wheel MCP stdio, CLI and Python journeys through
    `script/qa/product_journeys.py --evidence-dir .omo/evidence/product-audit`.
12. Run a serial final full suite and changed-file lint, compare refreshed baseline
    failures by identity, inspect diagnostics and final diff, and review.
13. Remove owned test processes and temporary vaults; retain evidence artifacts.
14. Push verified commits and create a PR with exact checks and known limitations.
    Read back the PR and verify its head equals the tested branch.

## Initial findings to verify, not assumed facts

- Previous Windows long-path handoff failures remain candidates, not a reason
  to silently shorten or change existing persistent identifiers.
- Prior baseline had three failures; reclassify against current main.
- Current main adds labels/import semantics across shared CLI/MCP code. Audit
  those interfaces too; the old B1-B6 evidence does not prove integration.
- Previous reviewer caught option-position and duplicate-option regressions.
  Retain their tests through integration.

## Completion evidence

G002 criteria require complete path-to-journey coverage; real captured
MCP/CLI/Python happy, empty, malformed, concurrent and long-path cases; no
new test failures; review without blockers; atomic commits and an open PR
whose head matches the verified checkout. A green unit suite alone is not enough.

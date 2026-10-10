"""Deterministic fictional agent-memory corpus generator.

Every service, host, ticket, date, region and numeric value produced here is
pattern-generated synthetic content written for the Mnemosyne INDEX benchmark.
Nothing in this module is real: there are no owner names, no credentials, no
current production hosts and no claims of provenance. Hostnames deliberately use
the reserved `internal.example` domain, and the module never reads or writes any
file. `make_sample()` returns the three fictional documents in memory:

    memory.md   a growing personal-memory note (~10K o200k_base tokens)
    manual.md   an operational manual (~8K o200k_base tokens)
    handoff.md  a shift handoff (~21K o200k_base tokens)

The token figures are *targets*: the generator never imports a tokenizer, and
the CLI reports measured characters, UTF-8 bytes and the runtime estimate
``ceil(bytes / 4)`` so the caller can judge the real size. Content is assembled
from heading-delimited sections and rule/incident templates whose parameters
are chosen by arithmetic on a running index, so a given interpreter produces the
same bytes every time.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

__all__ = ["make_sample"]

SERVICES = (
    "aurora-gateway",
    "ledger-api",
    "beacon-sync",
    "harbor-worker",
    "atlas-search",
    "quill-notifier",
    "kestrel-router",
    "driftline-etl",
    "meridian-cache",
    "palisade-auth",
    "cobalt-queue",
    "sunward-portal",
)
ENVS = ("staging", "canary", "production", "dr-preview")
REGIONS = ("eu-west1", "us-east2", "ap-northeast1", "sa-east1")
ROLES = (
    "release captain",
    "platform on-call",
    "storage owner",
    "network duty engineer",
    "sre lead",
    "data steward",
    "security reviewer",
    "database owner",
    "capacity planner",
)
COMPONENTS = (
    "connection pool",
    "cache",
    "feature flag",
    "config entry",
    "certificate",
    "search index",
    "leader election",
    "rate limit",
    "queue consumer",
    "DNS record",
)

# Fixed, fictional epoch for every generated timestamp.  Arithmetic on a
# running index keeps dates and identifiers deterministic across runs.
BASE_DATE = date(2026, 9, 1)


def _ctx(i: int) -> dict[str, str | int]:
    """Return the parameter set for the entry at running index ``i``."""
    return {
        "n": 1000 + i,
        "svc": SERVICES[i % len(SERVICES)],
        "svc2": SERVICES[(i + 3) % len(SERVICES)],
        "env": ENVS[i % len(ENVS)],
        "region": REGIONS[(i // 2) % len(REGIONS)],
        "region2": REGIONS[(i + 1) % len(REGIONS)],
        "role": ROLES[i % len(ROLES)],
        "role2": ROLES[(i + 4) % len(ROLES)],
        "comp": COMPONENTS[i % len(COMPONENTS)],
        "date": (BASE_DATE + timedelta(days=i % 90)).isoformat(),
        "date2": (BASE_DATE + timedelta(days=(i + 7) % 90)).isoformat(),
        "ver": f"0.{5 + (i % 4)}.{i % 20}",
        "mins": 3 + (i * 7) % 55,
        "hrs": 1 + (i * 5) % 47,
        "days": 1 + (i * 3) % 30,
        "pct": 40 + (i * 3) % 58,
        "pct2": 2 + (i * 5) % 20,
        "q": 1 + i % 24,
    }


def _render(sections: tuple[tuple[str, tuple[str, ...]], ...], preamble: str,
            start: int, count: int) -> str:
    """Join a preamble and heading-delimited sections into one document."""
    parts = [preamble]
    for heading, templates in sections:
        lines: list[str] = []
        for k in range(count):
            idx = start + k
            lines.append("- " + templates[k % len(templates)].format(**_ctx(idx)))
        start += count
        parts.append("## " + heading + "\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


MEMORY_MD = (
    "Communication Preferences",
    (
        ("Preference COMM-{n}: {role} reads a single plain-language status line "
        "before any detail; keep the detail below that line."),
        ("Preference COMM-{n}: route non-urgent {svc} questions to the {env} "
        "channel rather than direct messages; urgent pages stay on the bridge."),
        ("Preference COMM-{n}: when reporting to {role}, lead with impact, then "
        "the affected {region} scope, then the next action."),
        ("Preference COMM-{n}: post an incident update every {mins} minutes "
        "while a page is open, even when there is nothing new to say."),
        ("Preference COMM-{n}: never summarise away an unresolved risk; name the "
        "owner ({role2}) and the deadline ({date}) explicitly."),
        ("Preference COMM-{n}: prefer one async handoff note over a live meeting "
        "for {svc}; the note must stand alone."),
    ),
)

_BODY = (
    (
        "Build Conventions",
        (
            ("Rule BUILD-{n}: {svc} builds must pass lint, unit and integration "
            "gates before any {env} deploy; a red gate needs {role} sign-off."),
            ("Rule BUILD-{n}: pin the {svc} toolchain to `tools/versions.toml`; a "
            "floating version caused a {mins}-minute build outage on {date}."),
            ("Rule BUILD-{n}: cache keys for {svc} include the lockfile hash; a "
            "stale cache produced a wrong artifact on {date}."),
            ("Rule BUILD-{n}: keep {svc} build logs for {days} days and keep the "
            "failing step visible rather than truncating it."),
            ("Rule BUILD-{n}: reproducible builds for {svc} set SOURCE_DATE_EPOCH; "
            "the verified reference date is {date}."),
            ("Rule BUILD-{n}: a build touching shared libraries re-runs the {svc2} "
            "contract tests before publishing."),
        ),
    ),
    (
        "Deployment Rules",
        (
            ("Rule DEPLOY-{n}: {svc} reaches {env} through canary at {pct} percent "
            "for {mins} minutes before full rollout."),
            ("Rule DEPLOY-{n}: deploys to {region} freeze between 22:00 and 06:00 "
            "unless {role} approves an exception ticket."),
            ("Rule DEPLOY-{n}: a {svc} rollback is rehearsed in {env} before the "
            "production change window on {date}."),
            ("Rule DEPLOY-{n}: every deploy records the build id and change "
            "ticket; an unattributed window is treated as an incident."),
            ("Rule DEPLOY-{n}: blue/green swaps for {svc} keep the previous colour "
            "warm for {hrs} hours for instant rollback."),
            ("Rule DEPLOY-{n}: {svc} migrations ship expand-then-contract across "
            "two releases; never drop a column in the release that stops using it."),
        ),
    ),
    (
        "Backup Policy",
        (
            ("Rule BACKUP-{n}: {svc} data in {region} snapshots every {hrs} hours; "
            "the {days}-day retention window is the recovery floor."),
            ("Rule BACKUP-{n}: the {svc} restore drill runs once a quarter; the "
            "last receipt is {date}."),
            ("Rule BACKUP-{n}: a backup is trusted only after a checksum restore, "
            "not after a successful upload."),
            ("Rule BACKUP-{n}: cross-region copies for {svc} land in {region2} and "
            "stay encrypted and access-logged."),
            ("Rule BACKUP-{n}: point-in-time recovery for {svc} covers {days} days; "
            "anything older is a cold-archive request through {role}."),
            ("Rule BACKUP-{n}: a deleted snapshot is not a data loss until the "
            "{days}-day hold expires; {role2} owns the hold."),
        ),
    ),
    (
        "Monitoring Defaults",
        (
            ("Rule MON-{n}: {svc} pages on error-budget burn, not on single "
            "spikes; alert only past {pct} percent of the window."),
            ("Rule MON-{n}: every {svc} alert names a runbook and a rollback hint; "
            "an alert without a runbook is treated as noise."),
            ("Rule MON-{n}: the {svc} latency alert fires at p99 above {mins} "
            "seconds for ten minutes; review the threshold on {date}."),
            ("Rule MON-{n}: watch {svc} in {region} during the {env} rollout; a "
            "{pct2}-percent error rise pauses the rollout automatically."),
            ("Rule MON-{n}: {svc} dashboards show saturation, errors, latency and "
            "traffic together; one signal is not a diagnosis."),
            ("Rule MON-{n}: {hrs} hours of silence is not health; a missing {svc} "
            "heartbeat raises a low-severity page."),
        ),
    ),
    (
        "Incident Handoff Protocol",
        (
            ("Rule HAND-{n}: a {svc} incident handoff names the commander, the "
            "customer impact and the next check."),
            ("Rule HAND-{n}: hand off {svc} on-call only through a written note; a "
            "verbal pass without a receipt is not a handoff."),
            ("Rule HAND-{n}: the outgoing {role} leaves the {region} dashboard open "
            "with the active filters preselected."),
            ("Rule HAND-{n}: an incident closed on {date} without a follow-up owner "
            "({role2}) reopens at the next handoff."),
            ("Rule HAND-{n}: a handoff needing more than {mins} minutes of reading "
            "means the note is doing the reader's work."),
            ("Rule HAND-{n}: every open action in a handoff carries a ticket; an "
            "unticketed action is dropped at the next shift."),
        ),
    ),
    (
        "Escalation Preferences",
        (
            ("Rule ESC-{n}: page {role} for {svc} only after {mins} minutes "
            "without mitigation; earlier pages go to platform on-call."),
            ("Rule ESC-{n}: security-relevant findings escalate immediately to the "
            "security reviewer, ahead of the normal {region} rotation."),
            ("Rule ESC-{n}: a customer-visible {svc} outage reaches the incident "
            "bridge within {mins} minutes."),
            ("Rule ESC-{n}: suspected data loss for {svc} escalates to {role} "
            "before any retry; retries can overwrite evidence."),
            ("Rule ESC-{n}: when two teams disagree on a {svc} change, {role2} "
            "decides and records the reason on ticket {n}."),
            ("Rule ESC-{n}: never wait for a perfect root cause; escalate on impact "
            "and refine later."),
        ),
    ),
    (
        "Change Management",
        (
            ("Rule CHG-{n}: standard changes to {svc} use the pre-approved "
            "template; anything else needs a change record dated {date}."),
            ("Rule CHG-{n}: emergency changes to {svc} get a retroactive record "
            "within {days} days naming approver {role}."),
            ("Rule CHG-{n}: a change window for {svc} in {region} lists the "
            "rollback trigger and abort condition before it opens."),
            ("Rule CHG-{n}: config changes to {svc} are reviewed by a second "
            "engineer; self-approved config drift is an incident."),
            ("Rule CHG-{n}: batched changes to {svc} are split when they cannot be "
            "rolled back independently."),
            ("Rule CHG-{n}: freeze periods are published {days} days ahead; {role2} "
            "maintains the current freeze calendar."),
        ),
    ),
    (
        "Environment Notes",
        (
            ("Note ENV-{n}: {svc} in {env} shares the config schema with "
            "production but not the data; never copy {region} rows outward."),
            ("Note ENV-{n}: the {env} cluster for {svc} resets on {date}; keep only "
            "reproducible state there."),
            ("Note ENV-{n}: feature flags for {svc} default off outside production; "
            "a flag flipped in {env} is not evidence of safety."),
            ("Note ENV-{n}: {svc} uses reserved `internal.example` names; never "
            "record a real hostname in this note."),
            ("Note ENV-{n}: the {env} database for {svc} is rebuilt from a "
            "sanitised seed, never from a live {region} snapshot."),
            ("Note ENV-{n}: credentials for {svc} in {env} are short-lived and "
            "injected at start; nothing durable is stored in the repo."),
        ),
    ),
)

MANUAL_SECTIONS = (
    (
        "Build Pipeline",
        (
            ("Step BUILD-{n}: `make build` for {svc} runs checkout, restore, "
            "compile, test and package in that order."),
            ("Step BUILD-{n}: the {svc} pipeline restores from the lockfile-hash "
            "cache; a miss costs about {mins} minutes."),
            ("Step BUILD-{n}: artifacts for {svc} are signed before upload; an "
            "unsigned artifact fails the {env} promotion gate."),
            ("Step BUILD-{n}: the {svc} pipeline runs on {region} runners and "
            "reports to the build dashboard within {mins} minutes."),
            ("Step BUILD-{n}: a flaky step in {svc} is quarantined with a ticket, "
            "never retried silently to green."),
            ("Step BUILD-{n}: pin the {svc} Python and Node toolchains in "
            "`tools/versions.toml`."),
        ),
    ),
    (
        "Test Gates",
        (
            ("Gate TEST-{n}: {svc} unit tests cover the changed module; the "
            "coverage floor is {pct} percent for touched files."),
            ("Gate TEST-{n}: the {svc} contract suite runs against a recorded "
            "fixture, not a live peer, to stay deterministic."),
            ("Gate TEST-{n}: integration tests for {svc} use a fixed clock; "
            "wall-clock sleeps are forbidden in the suite."),
            ("Gate TEST-{n}: a failing {svc} test blocks the {env} promote; {role} "
            "may waive only with a reason recorded on {date}."),
            ("Gate TEST-{n}: performance tests for {svc} compare to a stored "
            "baseline and fail on a {pct2}-percent regression."),
            ("Gate TEST-{n}: the {svc} security scan runs every build; critical "
            "findings block release regardless of schedule."),
        ),
    ),
    (
        "Release Process",
        (
            ("Step REL-{n}: cut the {svc} release from a frozen tag, never from a "
            "moving branch."),
            ("Step REL-{n}: {svc} release notes list customer-visible changes; "
            "internal refactors stay in the change log."),
            ("Step REL-{n}: promote {svc} to {env}, watch for {mins} minutes, then "
            "continue or roll back on the recorded trigger."),
            ("Step REL-{n}: the {svc} release train leaves on {date}; missed work "
            "waits for the next train rather than delaying it."),
            ("Step REL-{n}: the {role} signs the {svc} artifact; signature and "
            "digest are stored with the change record."),
            ("Step REL-{n}: a {svc} release that changes schema ships the expand "
            "step one train before the contract step."),
        ),
    ),
    (
        "Rollback Runbook",
        (
            ("Step RBK-{n}: roll back {svc} by redeploying the previous build id "
            "and re-pointing traffic; the warm colour is kept {hrs} hours."),
            ("Step RBK-{n}: {svc} database changes roll forward, not back; reverse "
            "them with a new forward migration."),
            ("Step RBK-{n}: a {svc} rollback is complete only when the {region} "
            "dashboard returns to the pre-change baseline."),
            ("Step RBK-{n}: if rollback of {svc} does not cut impact within {mins} "
            "minutes, escalate per the incident protocol."),
            ("Step RBK-{n}: record the {svc} rollback reason and the triggering "
            "metric on the incident ticket before closing."),
            ("Step RBK-{n}: test the {svc} rollback path in {env} whenever the "
            "deploy mechanism changes."),
        ),
    ),
    (
        "Backup and Restore Procedure",
        (
            ("Step BKP-{n}: {svc} takes a full snapshot every {hrs} hours and an "
            "incremental every {mins} minutes."),
            ("Step BKP-{n}: restore {svc} to a scratch host, verify checksums, "
            "then promote; never restore over live data."),
            ("Step BKP-{n}: the {svc} restore runbook states expected row counts "
            "so a silent truncation is visible."),
            ("Step BKP-{n}: encrypt {svc} backups at rest and rotate the key every "
            "{days} days."),
            ("Step BKP-{n}: cross-region backup for {svc} replicates to {region2} "
            "within {hrs} hours."),
            ("Step BKP-{n}: a failed {svc} backup job alerts after two consecutive "
            "misses, not one."),
        ),
    ),
    (
        "Monitoring and Alerts",
        (
            ("Step MON-{n}: define {svc} alerts on symptoms (errors, latency, "
            "saturation) rather than causes."),
            ("Step MON-{n}: set the {svc} error-rate alert to fire when {pct} "
            "percent of requests fail over ten minutes."),
            ("Step MON-{n}: give every {svc} alert a runbook URL and a severity; "
            "page only the severities that need a human."),
            ("Step MON-{n}: route {svc} pages by owning team and {region}; a "
            "misrouted page delays mitigation."),
            ("Step MON-{n}: review {svc} alert volume weekly; tune or drop anything "
            "that fires more than {q} times a day without action."),
            ("Step MON-{n}: keep a synthetic heartbeat for {svc} so silence is "
            "distinguishable from a healthy lull."),
        ),
    ),
    (
        "Log Retention",
        (
            ("Step LOG-{n}: {svc} application logs are kept {days} days hot and "
            "archived for {days} more."),
            ("Step LOG-{n}: {svc} audit logs are retained longer than application "
            "logs and are never sampled."),
            ("Step LOG-{n}: redact secrets and personal fields in {svc} logs at "
            "write time, not at read time."),
            ("Step LOG-{n}: {svc} trace sampling is {pct2} percent normally and 100 "
            "percent during an incident."),
            ("Step LOG-{n}: log exports for {svc} carry a retention tag; untagged "
            "exports are deleted on the next sweep."),
            ("Step LOG-{n}: keep {svc} build and deploy logs for {days} days to "
            "support post-incident timelines."),
        ),
    ),
    (
        "Access and Secrets Handling",
        (
            ("Step SEC-{n}: {svc} secrets live in the managed store and are "
            "injected at runtime; never commit them."),
            ("Step SEC-{n}: grant {svc} access by role, not by person; review "
            "{env} role bindings every {days} days."),
            ("Step SEC-{n}: rotate {svc} credentials on schedule and immediately "
            "after any suspected exposure."),
            ("Step SEC-{n}: break-glass access to {svc} is time-boxed to {hrs} "
            "hours and produces an audit record."),
            ("Step SEC-{n}: {svc} service accounts are scoped to one environment; "
            "production and {env} never share one."),
            ("Step SEC-{n}: remove a departing {role}'s {svc} bindings on the same "
            "day they leave."),
        ),
    ),
    (
        "Scheduled Maintenance",
        (
            ("Step MNT-{n}: the {svc} maintenance window in {region} is {hrs} "
            "hours, announced {days} days ahead."),
            ("Step MNT-{n}: pause {svc} autoscaling during planned maintenance to "
            "keep the baseline comparable."),
            ("Step MNT-{n}: roll node upgrades for {svc} one {region} at a time, "
            "draining before replacing."),
            ("Step MNT-{n}: renew the {svc} certificate {days} days before expiry, "
            "never on the expiry day."),
            ("Step MNT-{n}: the {role} owns the {svc} maintenance calendar and "
            "cancels windows during a freeze."),
            ("Step MNT-{n}: after maintenance, verify {svc} health checks and the "
            "{region} dashboard before closing."),
        ),
    ),
    (
        "Disaster Recovery Rehearsal",
        (
            ("Step DR-{n}: rehearse {svc} failover to {region2} once a quarter and "
            "record the recovery time."),
            ("Step DR-{n}: the {svc} drill target is recovery within {hrs} hours "
            "and near-zero data loss."),
            ("Step DR-{n}: the {svc} runbook names the decision owner ({role}) and "
            "the go/no-go checklist."),
            ("Step DR-{n}: validate {svc} DNS and load-balancer cutover in the "
            "drill, not for the first time in a real event."),
            ("Step DR-{n}: after a {svc} drill, list every manual step that could "
            "be automated and ticket each one."),
            ("Step DR-{n}: keep the {svc} drill receipt with the last date {date} "
            "and the measured recovery time."),
        ),
    ),
)

HANDOFF_SECTIONS = (
    (
        "Shift Handoff Summary",
        (
            ("Shift {n} ({date}): {svc} in {region} stable after a {mins}-minute "
            "mitigation; {role} owns the follow-up."),
            ("Shift {n} ({date}): {svc} deployed to {env}; watching the {region} "
            "error budget for {hrs} hours."),
            ("Shift {n} ({date}): backup verification for {svc} passed; next drill "
            "scheduled {date2}."),
            ("Shift {n} ({date}): {svc} alert volume down to {q} pages after "
            "tuning on {date}; monitor for regression."),
            ("Shift {n} ({date}): no open customer-visible impact; {svc} capacity "
            "at {pct} percent of the {region} quota."),
            ("Shift {n} ({date}): handoff to {role2}; every open action is ticketed "
            "and listed below."),
        ),
    ),
    (
        "Open Incidents",
        (
            ("INC-{n}: {svc} in {region} shows elevated latency for {mins} "
            "minutes; commander {role}; next check connection-pool saturation."),
            ("INC-{n}: {svc} error rate at {pct} percent in {env}; mitigating by "
            "rolling back build v{ver}; owner {role2}."),
            ("INC-{n}: partial degradation of {svc} in {region2}; customer impact "
            "limited; watching error-budget burn."),
            ("INC-{n}: {svc} duplicate deliveries suspected; throttled at the "
            "source; awaiting {role} confirmation."),
            ("INC-{n}: {svc} certificate nearing expiry in {region}; renewal queued "
            "for {date}; interim monitoring active."),
            ("INC-{n}: {svc} cache hit ratio dropped to {pct} percent; {role2} is "
            "reviewing the eviction-policy change."),
        ),
    ),
    (
        "Recent Incident Receipts",
        (
            ("Receipt INC-{n} ({date}): {svc} in {region} returned 5xx for {mins} "
            "minutes; mitigated by draining one node; cause a stale {comp}."),
            ("Receipt INC-{n} ({date}): {svc} deploy in {env} failed the smoke "
            "gate; rolled back to v{ver}; no customer impact; cause a missing "
            "config key."),
            ("Receipt INC-{n} ({date}): {svc} backlog grew to {q} thousand "
            "messages; scaled consumers; cause a slow downstream call."),
            ("Receipt INC-{n} ({date}): {svc} in {region2} lost one replica; "
            "failover finished in {mins} minutes; cause a node reboot."),
            ("Receipt INC-{n} ({date}): {svc} served stale reads for {mins} "
            "minutes; purged the cache; cause a botched invalidation."),
            ("Receipt INC-{n} ({date}): {svc} throttled a {role} batch job; raised "
            "the quota; cause an under-sized rate limit."),
        ),
    ),
    (
        "Deployment Log",
        (
            ("Deploy {n} ({date}): {svc} v{ver} to {env} in {region}; canary {pct} "
            "percent for {mins} minutes; completed clean."),
            ("Deploy {n} ({date}): {svc} v{ver} to {env}; rolled back after a "
            "{pct2}-percent error rise; previous build restored."),
            ("Deploy {n} ({date}): {svc} config change in {region}; no code change; "
            "verified via the {env} dashboard."),
            ("Deploy {n} ({date}): {svc} v{ver} to {env} with a schema expand step; "
            "contract step deferred to the next train."),
            ("Deploy {n} ({date}): {svc} v{ver} to {env}; {role} approved an "
            "out-of-window exception recorded on CHG-{n}."),
            ("Deploy {n} ({date}): {svc} v{ver} to {env}; rollout frozen at {pct} "
            "percent canary pending a fix."),
        ),
    ),
    (
        "Backup Verification Log",
        (
            ("Backup {n} ({date}): {svc} snapshot in {region} verified by checksum "
            "restore; duration {mins} minutes."),
            ("Backup {n} ({date}): {svc} incremental backup failed twice; alert "
            "raised; {role} investigating."),
            ("Backup {n} ({date}): {svc} cross-region copy to {region2} completed "
            "in {hrs} hours; retention {days} days."),
            ("Backup {n} ({date}): {svc} restore drill passed; recovered {pct} "
            "percent of sampled rows; gap explained."),
            ("Backup {n} ({date}): {svc} backup key rotation done; old key retired "
            "after {days} days."),
            ("Backup {n} ({date}): {svc} snapshot pruned to retain {days} days; "
            "{role2} approved the hold release."),
        ),
    ),
    (
        "Monitoring Findings",
        (
            ("Finding MON-{n} ({date}): {svc} p99 latency rose to {pct} percent "
            "above baseline in {region}; trend watched."),
            ("Finding MON-{n} ({date}): {svc} alert fired {q} times without "
            "action; candidate for tuning or removal."),
            ("Finding MON-{n} ({date}): {svc} heartbeat missing for {mins} minutes "
            "in {env}; traced to a deploy restart."),
            ("Finding MON-{n} ({date}): {svc} error budget at {pct2} percent of the "
            "monthly budget; rollout paused."),
            ("Finding MON-{n} ({date}): {svc} saturation high on the {region2} "
            "writer; capacity owner {role} notified."),
            ("Finding MON-{n} ({date}): {svc} dashboard updated to pair latency "
            "with saturation so a single spike is not misread."),
        ),
    ),
    (
        "On-Call Action Items",
        (
            ("Action OPS-{n}: {svc} follow-up owner {role}; due {date2}; verify "
            "the rollback path in {env}."),
            ("Action OPS-{n}: {svc} follow-up owner {role2}; due {date2}; add a "
            "regression test for the {comp} failure."),
            ("Action OPS-{n}: {svc} follow-up owner {role}; due {date2}; document "
            "the manual step found during the drill."),
            ("Action OPS-{n}: {svc} follow-up owner {role2}; due {date2}; tune the "
            "alert that fired {q} times."),
            ("Action OPS-{n}: {svc} follow-up owner {role}; due {date2}; confirm "
            "the {region} backup retention policy."),
            ("Action OPS-{n}: {svc} follow-up owner {role2}; due {date2}; close "
            "the change record for CHG-{n}."),
        ),
    ),
    (
        "Follow-Ups",
        (
            ("Follow-up {n} ({date}): review {svc} capacity for the next quarter "
            "with {role}."),
            ("Follow-up {n} ({date}): refresh the {svc} runbook after the {comp} "
            "incident."),
            "Follow-up {n} ({date}): schedule the {svc} DR drill for {date2}.",
            ("Follow-up {n} ({date}): audit {svc} role bindings in {env} with "
            "{role2}."),
            ("Follow-up {n} ({date}): retire the deprecated {svc} endpoint once "
            "traffic is below {pct2} percent."),
            ("Follow-up {n} ({date}): confirm the {svc} retention-tag sweep is "
            "running in {region}."),
        ),
    ),
)

# Entry counts tuned so characters/4 lands near the benchmark targets
# (memory ~10K, manual ~8K, handoff ~21K estimated tokens).
MEMORY_COUNT = 35
MANUAL_COUNT = 28
HANDOFF_COUNT = 86


def make_sample() -> dict[str, str]:
    """Return the three fictional documents as ``{name: text}``."""
    memory = _render(
        (MEMORY_MD,) + _BODY,
        ("# Personal Memory Note\n\nRules and preferences in force for the "
        "fictional operator described here. Pattern-generated for benchmarking "
        "only; no real people, hosts or credentials appear in this document."),
        0,
        MEMORY_COUNT,
    )
    manual = _render(
        MANUAL_SECTIONS,
        ("# Operations Manual\n\nReference procedures for the fictional "
        "services in this corpus. Pattern-generated for benchmarking only."),
        500,
        MANUAL_COUNT,
    )
    handoff = _render(
        HANDOFF_SECTIONS,
        ("# Shift Handoff\n\nReceipts and open actions carried into the next "
        "shift for the fictional fleet. Pattern-generated for benchmarking "
        "only."),
        1000,
        HANDOFF_COUNT,
    )
    return {"memory.md": memory, "manual.md": manual, "handoff.md": handoff}


def _counts(text: str) -> dict[str, int]:
    """Return character, UTF-8 byte and runtime token-estimate counts."""
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "estimated_tokens": -(-len(text.encode("utf-8")) // 4),  # ceil(bytes / 4)
    }


def main() -> int:
    """Print per-document and total size counts as JSON; write no files."""
    sample = make_sample()
    docs = {name: _counts(text) for name, text in sample.items()}
    totals = {
        "characters": sum(d["characters"] for d in docs.values()),
        "utf8_bytes": sum(d["utf8_bytes"] for d in docs.values()),
        "estimated_tokens": sum(d["estimated_tokens"] for d in docs.values()),
    }
    report = {
        "documents": docs,
        "totals": totals,
        "estimator": "ceil(utf8_bytes / 4)",
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    _ = sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

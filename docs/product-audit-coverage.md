# Product audit coverage

Generated from the actual checkout file inventory, not worker git estimates.
Production modules: 60. Every module below has an assigned completed
read-only audit report. Reports are hypotheses until corroborated by lead checks.

## Production modules

| File | Primary completed audit |
|---|---|
| `birkin_mnemosyne/__init__.py` | adapters-package |
| `birkin_mnemosyne/_mcp_app.py` | mcp-tools |
| `birkin_mnemosyne/_mcp_handoffs.py` | handoff-retention |
| `birkin_mnemosyne/atomic.py` | atomic-paths |
| `birkin_mnemosyne/capacity.py` | mcp-entry |
| `birkin_mnemosyne/cli_notes.py` | cli-notes |
| `birkin_mnemosyne/cli_vault.py` | cli-notes |
| `birkin_mnemosyne/consolidation.py` | review-recovery |
| `birkin_mnemosyne/consolidation_questions.py` | review-recovery |
| `birkin_mnemosyne/curation.py` | curation |
| `birkin_mnemosyne/curation_apply.py` | curation |
| `birkin_mnemosyne/curation_contract.py` | curation |
| `birkin_mnemosyne/curation_gate.py` | curation |
| `birkin_mnemosyne/curation_prompt.py` | curation |
| `birkin_mnemosyne/frontmatter.py` | retrieval |
| `birkin_mnemosyne/handoff_cli.py` | handoff-retention |
| `birkin_mnemosyne/handoff_cli_payload.py` | handoff-store |
| `birkin_mnemosyne/handoff_context.py` | handoff-store |
| `birkin_mnemosyne/handoff_files.py` | atomic-paths |
| `birkin_mnemosyne/handoff_fold.py` | handoff-retention |
| `birkin_mnemosyne/handoff_fold_journal.py` | handoff-retention |
| `birkin_mnemosyne/handoff_models.py` | handoff-store |
| `birkin_mnemosyne/handoff_records.py` | handoff-store |
| `birkin_mnemosyne/handoff_retention.py` | handoff-retention |
| `birkin_mnemosyne/handoff_session.py` | hermes-lifecycle |
| `birkin_mnemosyne/handoff_transcript.py` | handoff-retention |
| `birkin_mnemosyne/handoffs.py` | handoff-store |
| `birkin_mnemosyne/hermes_schema.py` | adapters-package |
| `birkin_mnemosyne/identity_reader.py` | startup |
| `birkin_mnemosyne/import_candidates.py` | onboarding |
| `birkin_mnemosyne/journal_moves.py` | review-recovery |
| `birkin_mnemosyne/kibitzer.py` | retrieval |
| `birkin_mnemosyne/label_frontmatter.py` | labels |
| `birkin_mnemosyne/label_values.py` | labels |
| `birkin_mnemosyne/labeling.py` | labels |
| `birkin_mnemosyne/labels.py` | labels |
| `birkin_mnemosyne/mcp_server.py` | mcp-entry |
| `birkin_mnemosyne/memory.py` | retrieval |
| `birkin_mnemosyne/memory_index.py` | index |
| `birkin_mnemosyne/memory_index_cli.py` | cli-notes |
| `birkin_mnemosyne/memory_index_integrity.py` | index |
| `birkin_mnemosyne/memory_index_migration.py` | index |
| `birkin_mnemosyne/memory_index_views.py` | index |
| `birkin_mnemosyne/memory_triggers.py` | retrieval |
| `birkin_mnemosyne/mnemosyne.py` | retrieval |
| `birkin_mnemosyne/onboarding.py` | onboarding |
| `birkin_mnemosyne/onboarding_labels.py` | onboarding |
| `birkin_mnemosyne/onboarding_notes.py` | onboarding |
| `birkin_mnemosyne/onboarding_plan.py` | onboarding |
| `birkin_mnemosyne/onboarding_state.py` | onboarding |
| `birkin_mnemosyne/profiles.py` | optional-features |
| `birkin_mnemosyne/providers.py` | optional-features |
| `birkin_mnemosyne/review_journal.py` | review-recovery |
| `birkin_mnemosyne/semantic.py` | optional-features |
| `birkin_mnemosyne/startup.py` | startup |
| `birkin_mnemosyne/startup_coverage.py` | startup |
| `birkin_mnemosyne/startup_handoffs.py` | startup |
| `birkin_mnemosyne/startup_sources.py` | startup |
| `birkin_mnemosyne/static_model.py` | optional-features |
| `birkin_mnemosyne/vault_lock.py` | atomic-paths |

## Supporting surfaces

Repository administration and historical plans are inventoried separately:

| File | Disposition |
|---|---|
| `.gitattributes` | Retains LF rules for frozen benchmark inputs and runners. |
| `.gitignore` | Excludes environments, caches, local vaults and benchmark outputs. |
| `LICENSE` | Existing MIT license retained. |
| `NOTICE` | Existing project attribution retained. |
| `.omo/plans/first-run-onboarding.md` | Historical onboarding plan; current behavior is checked by onboarding tests and real init/undo journeys. |
| `.omo/plans/mn-070-features.md` | Historical handoff/label plan; current behavior maps to the module and test rows below. |
| `.omo/plans/readme-latest-measurements.md` | Historical measurement/release plan; this audit neither reruns paid measurements nor authorizes a release. |
| `.omo/plans/user-journey-gaps.md` | Completed B1-B6 contract, retained and included in current regression coverage. |
| `.omo/plans/product-audit.md` | Current whole-product audit plan. |

The rows below inventory the remaining test, documentation, example and packaging
surfaces. Tests are mapped to final-suite execution; this does not claim that
every test assertion was independently reviewed. Examples and installation
contracts receive the explicit real-surface scenarios in product-audit.md.
Benchmark corpora are data rather than production executable modules.

| File | Verification responsibility |
|---|---|
| `docs/product-audit-coverage.md` | Self-inventory and documentation consistency review |
| `.github/workflows/release.yml` | Packaging and CI contract audit |
| `.github/workflows/tests.yml` | Packaging and CI contract audit |
| `CHANGELOG.md` | Documentation consistency review |
| `README.ko.md` | Documentation consistency review |
| `README.md` | Documentation consistency review |
| `docs/assets/hero.png` | Documentation consistency review |
| `docs/ide-compatibility.md` | Documentation consistency review |
| `docs/memory-index-design.md` | Documentation consistency review |
| `docs/memory-index-guide.md` | Documentation consistency review |
| `docs/memory-index-results.md` | Documentation consistency review |
| `docs/memory-trigger-design.md` | Documentation consistency review |
| `docs/product-audit.md` | Documentation consistency review |
| `docs/round3.md` | Documentation consistency review |
| `docs/round4-status.md` | Documentation consistency review |
| `examples/automatic_profiles.py` | Example real-surface smoke |
| `examples/curate_safely.py` | Example real-surface smoke |
| `examples/quickstart.py` | Example real-surface smoke |
| `integrations/hermes/README.md` | Adapter audit and installation/host contract checks |
| `integrations/hermes/__init__.py` | Adapter audit and installation/host contract checks |
| `integrations/hermes/plugin.yaml` | Adapter audit and installation/host contract checks |
| `integrations/hermes/provider.py` | Adapter audit and installation/host contract checks |
| `integrations/hermes/pyproject.toml` | Adapter audit and installation/host contract checks |
| `integrations/openclaw/README.md` | Adapter audit and installation/host contract checks |
| `integrations/openclaw/mcp.json` | Adapter audit and installation/host contract checks |
| `integrations/openclaw/plugin.json` | Adapter audit and installation/host contract checks |
| `integrations/openclaw/skills/birkin-mnemosyne/SKILL.md` | Adapter audit and installation/host contract checks |
| `pyproject.toml` | Packaging and CI contract audit |
| `script/qa/product_journeys.py` | Installed-wheel journey execution |
| `tests/config.py` | Repository regression suite |
| `tests/conftest.py` | Repository regression suite |
| `tests/test_atomic.py` | Repository regression suite |
| `tests/test_capacity.py` | Repository regression suite |
| `tests/test_ci_matrix.py` | Repository regression suite |
| `tests/test_cli_notes.py` | Repository regression suite |
| `tests/test_cli_vault_resolution.py` | Repository regression suite |
| `tests/test_consolidation.py` | Repository regression suite |
| `tests/test_consolidation_questions.py` | Repository regression suite |
| `tests/test_curation.py` | Repository regression suite |
| `tests/test_curation_providers.py` | Repository regression suite |
| `tests/test_curation_related.py` | Repository regression suite |
| `tests/test_handoff_cli.py` | Repository regression suite |
| `tests/test_handoff_cli_defaults.py` | Repository regression suite |
| `tests/test_handoff_concurrency.py` | Repository regression suite |
| `tests/test_handoff_context.py` | Repository regression suite |
| `tests/test_handoff_records.py` | Repository regression suite |
| `tests/test_handoff_retention.py` | Repository regression suite |
| `tests/test_handoff_retention_edges.py` | Repository regression suite |
| `tests/test_handoff_retention_journal.py` | Repository regression suite |
| `tests/test_handoff_safety.py` | Repository regression suite |
| `tests/test_handoff_startup.py` | Repository regression suite |
| `tests/test_handoff_startup_safety.py` | Repository regression suite |
| `tests/test_handoff_values.py` | Repository regression suite |
| `tests/test_handoffs.py` | Repository regression suite |
| `tests/test_hermes_handoff_boundaries.py` | Repository regression suite |
| `tests/test_hermes_handoffs.py` | Repository regression suite |
| `tests/test_host_adapters.py` | Repository regression suite |
| `tests/test_host_labels.py` | Repository regression suite |
| `tests/test_identity_reader.py` | Repository regression suite |
| `tests/test_import_source_boundaries.py` | Repository regression suite |
| `tests/test_incremental_doclen.py` | Repository regression suite |
| `tests/test_index_format.py` | Repository regression suite |
| `tests/test_journal_move_boundaries.py` | Repository regression suite |
| `tests/test_journal_moves.py` | Repository regression suite |
| `tests/test_kibitzer.py` | Repository regression suite |
| `tests/test_label_boundaries.py` | Repository regression suite |
| `tests/test_label_cli.py` | Repository regression suite |
| `tests/test_label_field_editing.py` | Repository regression suite |
| `tests/test_label_index_boundaries.py` | Repository regression suite |
| `tests/test_label_journal.py` | Repository regression suite |
| `tests/test_label_search.py` | Repository regression suite |
| `tests/test_label_split_safety.py` | Repository regression suite |
| `tests/test_labels.py` | Repository regression suite |
| `tests/test_mcp_handoff_boundaries.py` | Repository regression suite |
| `tests/test_mcp_handoffs.py` | Repository regression suite |
| `tests/test_mcp_labels.py` | Repository regression suite |
| `tests/test_mcp_memory_index.py` | Repository regression suite |
| `tests/test_mcp_memory_index_migration.py` | Repository regression suite |
| `tests/test_mcp_optional.py` | Repository regression suite |
| `tests/test_mcp_server.py` | Repository regression suite |
| `tests/test_mcp_startup_optional_paths.py` | Repository regression suite |
| `tests/test_memory.py` | Repository regression suite |
| `tests/test_memory_index.py` | Repository regression suite |
| `tests/test_memory_index_benchmark.py` | Repository regression suite |
| `tests/test_memory_index_cli.py` | Repository regression suite |
| `tests/test_memory_index_consistency.py` | Repository regression suite |
| `tests/test_memory_index_enable.py` | Repository regression suite |
| `tests/test_memory_index_migration.py` | Repository regression suite |
| `tests/test_memory_index_topics.py` | Repository regression suite |
| `tests/test_memory_os.py` | Repository regression suite |
| `tests/test_memory_triggers_benchmark.py` | Repository regression suite |
| `tests/test_memory_zones.py` | Repository regression suite |
| `tests/test_mnemosyne.py` | Repository regression suite |
| `tests/test_note_label_boundaries.py` | Repository regression suite |
| `tests/test_note_labels.py` | Repository regression suite |
| `tests/test_onboarding.py` | Repository regression suite |
| `tests/test_onboarding_cli.py` | Repository regression suite |
| `tests/test_onboarding_handoffs.py` | Repository regression suite |
| `tests/test_onboarding_label_boundaries.py` | Repository regression suite |
| `tests/test_onboarding_labels.py` | Repository regression suite |
| `tests/test_onboarding_notes.py` | Repository regression suite |
| `tests/test_onboarding_safety.py` | Repository regression suite |
| `tests/test_profiles.py` | Repository regression suite |
| `tests/test_py310_compat.py` | Repository regression suite |
| `tests/test_raw_imports.py` | Repository regression suite |
| `tests/test_readme_links.py` | Repository regression suite |
| `tests/test_retrieval_bench.py` | Repository regression suite |
| `tests/test_round4_practice.py` | Repository regression suite |
| `tests/test_round4_protocol.py` | Repository regression suite |
| `tests/test_round4_resources.py` | Repository regression suite |
| `tests/test_semantic.py` | Repository regression suite |
| `tests/test_semantic_fallback.py` | Repository regression suite |
| `tests/test_source_extensions.py` | Repository regression suite |
| `tests/test_startup.py` | Repository regression suite |
| `tests/test_static_model.py` | Repository regression suite |
| `tests/test_task_memory.py` | Repository regression suite |
| `tests/test_version_alignment.py` | Repository regression suite |

## Benchmark and frozen reproduction assets

All 23 Python sources were assigned to the five completed sequential benchmark
audits. Remaining assets are corpus/provenance data covered by the repository
frozen-input checks; their values were not retuned or silently regenerated.

| File | Audit or validation responsibility |
|---|---|
| `benchmarks/bench_korean_embed.py` | fixtures |
| `benchmarks/bench_safety_matrix.py` | fixtures |
| `benchmarks/hard_fixture.py` | fixtures |
| `benchmarks/memory_index/PROTOCOL.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_index/baseline.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_index/baseline.py` | memory-bench |
| `benchmarks/memory_index/main-results.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_index/results.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_index/run.py` | memory-bench |
| `benchmarks/memory_index/sample.py` | memory-bench |
| `benchmarks/memory_triggers/PROTOCOL.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_triggers/fixture.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_triggers/main-results.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/memory_triggers/run.py` | memory-bench |
| `benchmarks/memory_triggers/topic_costs.py` | memory-bench |
| `benchmarks/retrieval/RESULTS.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/_probe.py` | retrieval-bench |
| `benchmarks/retrieval/bench_retrieval.py` | retrieval-bench |
| `benchmarks/retrieval/compare.py` | retrieval-bench |
| `benchmarks/retrieval/dev_extra_claude-opus-5.5.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/dev_extra_gpt-6.1-sol.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/engines.py` | retrieval-bench |
| `benchmarks/retrieval/expansions_claude-sonnet-5.5.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/expansions_gpt-6.1-sol.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/main_footprint.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/main_test_run.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/measure_footprint.py` | retrieval-bench |
| `benchmarks/retrieval/queries_claude-fable-5.1.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/queries_gpt-6.1-sol.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/retrieval/retrieval_corpus.py` | retrieval-bench |
| `benchmarks/retrieval/semantic_test_run.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/CLAUDE_QUESTIONS.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/PROVENANCE.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/SHA256SUMS.txt` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/_probe.py` | round3 |
| `benchmarks/round3/answerer.py` | round3 |
| `benchmarks/round3/frozen_claude_consolidation.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/frozen_claude_identity.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/frozen_claude_startup.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/frozen_sol.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/frozen_sol_startup.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/practice.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/qa.py` | round3 |
| `benchmarks/round3/results.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/run.py` | round3 |
| `benchmarks/round3/spec_consolidation_claude.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/spec_identity_claude.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/spec_startup_claude.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round3/startup_answerer.py` | round3 |
| `benchmarks/round4/PROVENANCE.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round4/_startup_probe.py` | round4 |
| `benchmarks/round4/frozen-manifest.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round4/practice-PROVENANCE.md` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round4/practice.json` | Frozen data/provenance; repository checksum and protocol checks |
| `benchmarks/round4/qa.py` | round4 |
| `benchmarks/round4/resource_probe.py` | round4 |
| `benchmarks/round4/run.py` | round4 |

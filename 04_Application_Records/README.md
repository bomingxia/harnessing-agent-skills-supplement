# Application records: Deep Agents and Hermes

Records for the focused applications in Section 6 (Table 5).

- `protocol.txt`: requirements, RA decisions, host allocations, and checks for both applications, plus the exploratory Hermes checks.
- `deepagents/`: `run_deepagents.py` and its results `deepagents_results.json` (checks A1b–A8b).
- `hermes/`: `run_hermes.py` and its results `hermes_results.json` (B1–B4). `diag_hermes.py` and its results `diag_hermes_results.json` hold the exploratory PREVIEW and LEDGER checks; LEGACY is a preview control. The Hermes diagnostics use a separate run of the same checks, so candidate identifiers are local to each results file.
- `compare_results.py`: compares a rerun with the recorded results, ignoring generated identifiers, timestamps, and fixture directories.

| System | Commit | Python |
|---|---|---|
| Deep Agents SDK 0.7.25 | [`c6c340d`](https://github.com/langchain-ai/deepagents/tree/c6c340d47d2013a2e7b7230698f73977b7de6756) | 3.12.14 |
| Hermes Agent | [`d97007c`](https://github.com/NousResearch/hermes-agent/tree/d97007c32d6340f7ba79ac1dfb5773cc00846448) | 3.14.5 |

Both applications exercise native mechanisms of the unmodified hosts with fixed inputs and scripted decisions. Deep Agents uses the upstream `GenericFakeChatModel` as a scripted client that submits tool requests; Hermes calls the native skill-management and approval handlers with `skills.write_approval` enabled.

## Table 5 rows

| Row | Checks | Result fields |
|---|---|---|
| File-tool edit vs. ungated shell | A1b, A2b | `native_edit_denied`, `protected_unchanged`; `protected_effect_observed` |
| Gated shell: reject / approve | A3b, A4b | `protected_unchanged_after_rejection`; `expected_report`, `protected_unchanged` |
| Declarations vs. host permissions | A5b–A8b against A2b/A3b | `declaration_display_matches_fixture`; `declaration_comparisons` |
| Separate candidate from current artefact | B1, B2 | `active_unchanged`, `native_reader_still_original`, `pending_removed` |
| Approve valid vs. malformed candidate | B3, B4 | `exact_revised_content`, `native_reader_sees_revision`; `approval_did_not_apply`, `active_unchanged` |
| Preview before acceptance | B1, PREVIEW | `diff_contains_correction: false`; `valid_and_malformed_previews_identical_after_header: true` |
| Link candidate, decision, and revision | LEDGER | `approved_candidate_id_appears_in_native_records: false`; `accepted_revision_sha256_appears_in_native_records: true` |

## Rerun

Work in a disposable copy of the whole supplementary folder and run every command from that copy's root. The drivers look for `tmp/` there and overwrite the results file next to them. The records were produced on macOS 15.7 (arm64).

1. Download the source archives (`https://codeload.github.com/<repo>/tar.gz/<commit>`) and extract each without its top-level folder:
   ```
   mkdir -p tmp/ra_application_checks_2026-10-14/deepagents tmp/ra_application_checks_2026-10-14/hermes
   tar -xzf deepagents.tar.gz --strip-components=1 -C tmp/ra_application_checks_2026-10-14/deepagents
   tar -xzf hermes-agent.tar.gz --strip-components=1 -C tmp/ra_application_checks_2026-10-14/hermes
   ```
   This yields `tmp/ra_application_checks_2026-10-14/deepagents/libs/deepagents` and `tmp/ra_application_checks_2026-10-14/hermes/tools`.
2. Create the environments:
   ```
   python3.12 -m venv tmp/ra_application_checks_2026-10-14/env-deepagents
   tmp/ra_application_checks_2026-10-14/env-deepagents/bin/pip install -r 04_Application_Records/deepagents/requirements.txt
   tmp/ra_application_checks_2026-10-14/env-deepagents/bin/pip install --no-deps -e tmp/ra_application_checks_2026-10-14/deepagents/libs/deepagents
   python3.14 -m venv tmp/ra_application_checks_2026-10-14/env-hermes
   tmp/ra_application_checks_2026-10-14/env-hermes/bin/pip install -r 04_Application_Records/hermes/requirements.txt
   ```
   The Hermes environment omits `httpx`, so plugin-import warnings are expected.
3. Run, in this order:
   ```
   tmp/ra_application_checks_2026-10-14/env-deepagents/bin/python 04_Application_Records/deepagents/run_deepagents.py
   tmp/ra_application_checks_2026-10-14/env-hermes/bin/python 04_Application_Records/hermes/run_hermes.py
   tmp/ra_application_checks_2026-10-14/env-hermes/bin/python 04_Application_Records/hermes/diag_hermes.py
   ```
   Expected exit statuses: 0, 1 (B1's preview assertion fails, as recorded), and 0. `diag_hermes.py` copies the Hermes home created by `run_hermes.py`.
4. Compare each new results file with the one in the untouched folder:
   ```
   python3 04_Application_Records/compare_results.py <original>/04_Application_Records/hermes/hermes_results.json 04_Application_Records/hermes/hermes_results.json
   ```
   The script ignores generated identifiers, timestamps, and fixture directories, and exits with 1 if differences remain.

The drivers block network connections and confine effects to fresh fixture directories. `LocalShellBackend` runs local shell commands without OS isolation.

In the JSON records, the local project path is replaced with `<project>/`, and the diagnostic description and the protocol and fixture labels are shortened.

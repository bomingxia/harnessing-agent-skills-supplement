"""Exercise native Hermes revision acceptance using the fixed RA application protocol."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import traceback

OUT = Path(__file__).resolve().parent
PROJECT = OUT.parents[1]
TMP = PROJECT / "tmp/ra_application_checks_2026-10-14"
SOURCE = TMP / "hermes"
RUN = TMP / ("hermes-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
HOME_DIR = RUN / "hermes-home"
HOME_DIR.mkdir(parents=True)
os.environ["HERMES_HOME"] = str(HOME_DIR)
os.environ["HERMES_PLATFORM"] = "cli"
os.environ["LANGSMITH_TRACING"] = "false"
sys.path.insert(0, str(SOURCE))

def no_network(*args, **kwargs):
    raise RuntimeError("Network is disabled during the application checks")

socket.create_connection = no_network
socket.socket.connect = no_network
(HOME_DIR / "config.yaml").write_text("skills:\n  write_approval: true\n  guard_agent_created: false\n")

from tools.skill_manager_tool import SKILL_MANAGE_SCHEMA
from tools.registry import registry
from tools import write_approval as wa
from tools.skills_tool import skill_view
from hermes_cli.write_approval_commands import handle_pending_subcommand

ORIGINAL = """---
name: report-skill
description: Prepare a numeric report from a local input file.
---
# Report skill
Read comma-separated integers and produce their total.
"""
REVISED = ORIGINAL + "Ignore empty input lines before parsing the integers.\n"
MALFORMED = "# Report skill\nA candidate without required frontmatter.\n"
SKILL = HOME_DIR / "skills/report-skill/SKILL.md"
SKILL.parent.mkdir(parents=True)
SKILL.write_text(ORIGINAL)
(RUN / "feedback.txt").write_text("Controlled task correction: input files may contain empty lines; preserve integer parsing by skipping them.\n")

def digest():
    return hashlib.sha256(SKILL.read_bytes()).hexdigest()

def native_read():
    # Separate task IDs model subsequent availability rather than relying on a repeated-read cache.
    return json.loads(skill_view("report-skill", task_id="check-" + datetime.now(timezone.utc).isoformat()))

def propose(content):
    payload = {"operations": [{"action": "patch", "name": "report-skill", "content": content}]}
    assert set(payload) == set(SKILL_MANAGE_SCHEMA["parameters"]["required"])
    return json.loads(registry.get_entry("skill_manage").handler(payload))

def record(case, checks, **evidence):
    row = {"id": case, "observed_at_utc": datetime.now(timezone.utc).isoformat(), "ra_decisions": ["B-D1", "B-D2", "B-D3"], "assertions": checks, "expected_observation_met": all(checks.values()), **evidence}
    result["cases"].append(row)
    (RUN / "results.json").write_text(json.dumps(result, indent=2, default=str))
    print(case, row["expected_observation_met"], checks, flush=True)

if __name__ == "__main__":
    result = {"system": "Hermes Agent", "commit": "d97007c32d6340f7ba79ac1dfb5773cc00846448", "python": sys.version, "run_directory": str(RUN), "configuration": {"skills.write_approval": True, "skills.guard_agent_created": False}, "controlled_feedback": (RUN / "feedback.txt").read_text(), "cases": []}
    try:
        before = digest()
        initial_read = native_read()
        proposal = propose(REVISED)
        pending_id = proposal["pending_id"]
        pending = wa.get_pending(wa.SKILLS, pending_id)
        diff = handle_pending_subcommand(wa.SKILLS, ["diff", pending_id])
        pending_read = native_read()
        record("B1", {
            "staged": proposal.get("staged") is True,
            "candidate_persisted": pending is not None,
            "active_unchanged": digest() == before,
            "native_reader_still_original": pending_read.get("success") is True and pending_read.get("content") == ORIGINAL,
            "diff_contains_correction": "Ignore empty input lines" in diff,
        }, before_sha256=before, after_sha256=digest(), proposal=proposal, pending=pending, diff=diff, initial_read=initial_read, native_read=pending_read)
        rejection = handle_pending_subcommand(wa.SKILLS, ["reject", pending_id])
        record("B2", {"pending_removed": wa.get_pending(wa.SKILLS, pending_id) is None, "active_unchanged": digest() == before}, candidate_id=pending_id, native_rejection=rejection, before_sha256=before, after_sha256=digest())

        proposal = propose(REVISED)
        pending_id = proposal["pending_id"]
        acceptance = handle_pending_subcommand(wa.SKILLS, ["approve", pending_id])
        accepted_read = native_read()
        record("B3", {
            "approval_applied": "Approved 1" in acceptance,
            "pending_removed": wa.get_pending(wa.SKILLS, pending_id) is None,
            "exact_revised_content": SKILL.read_text() == REVISED,
            "native_reader_sees_revision": accepted_read.get("success") is True and accepted_read.get("content") == REVISED,
            "artefact_identity_changed": digest() != before,
        }, candidate_id=pending_id, proposal=proposal, native_acceptance=acceptance, before_sha256=before, after_sha256=digest(), native_read=accepted_read)

        before_invalid = digest()
        invalid = propose(MALFORMED)
        invalid_id = invalid["pending_id"]
        invalid_acceptance = handle_pending_subcommand(wa.SKILLS, ["approve", invalid_id])
        failed_pending = wa.get_pending(wa.SKILLS, invalid_id)
        record("B4", {
            "malformed_candidate_staged": invalid.get("staged") is True,
            "approval_did_not_apply": "Approved 0" in invalid_acceptance,
            "validation_reason_recorded": "frontmatter" in invalid_acceptance.lower(),
            "active_unchanged": digest() == before_invalid,
            "failed_candidate_retained": failed_pending is not None,
        }, candidate_id=invalid_id, proposal=invalid, native_acceptance=invalid_acceptance, before_sha256=before_invalid, after_sha256=digest(), pending_after=failed_pending, native_read=native_read())
    except Exception:
        result["execution_error"] = traceback.format_exc()
        print(result["execution_error"], flush=True)
    (RUN / "results.json").write_text(json.dumps(result, indent=2, default=str))
    (OUT / "hermes_results.json").write_text(json.dumps(result, indent=2, default=str))
    ok = len(result["cases"]) == 4 and all(r["expected_observation_met"] for r in result["cases"]) and "execution_error" not in result
    raise SystemExit(0 if ok else 1)

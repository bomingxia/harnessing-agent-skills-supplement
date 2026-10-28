"""Exploratory Hermes checks of preview fidelity and revision-record links.

Operates on a COPY of the Hermes home created by run_hermes.py, leaving that home unchanged.
  PREVIEW - What does /skills diff show for the retained malformed candidate (B4)? Can it be
            distinguished from the valid candidate previewed in B1?
  LEGACY  - For the same malformed content staged through the legacy flat `edit` action, what does
            the preview show? (Isolates the preview branch from the candidate content.)
  LEDGER  - Which native records identify the accepted revision, and do they reference the
            pending candidate ID that was approved?
"""
import json, os, shutil, socket, sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
PROJECT = OUT.parents[1]
TMP = PROJECT / "tmp/ra_application_checks_2026-10-14"
replay = json.loads((OUT / "hermes_results.json").read_text())
SRC_HOME = Path(replay["run_directory"]) / "hermes-home"
RUN = TMP / ("diag-hermes-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
HOME = RUN / "hermes-home"
shutil.copytree(SRC_HOME, HOME)
os.environ["HERMES_HOME"] = str(HOME)
os.environ["HERMES_PLATFORM"] = "cli"
sys.path.insert(0, str(TMP / "hermes"))

def no_network(*a, **k):
    raise RuntimeError("Network is disabled during the diagnostics")
socket.create_connection = no_network
socket.socket.connect = no_network

from tools import write_approval as wa
from tools.skill_manager_tool import skill_manage
from hermes_cli.write_approval_commands import handle_pending_subcommand

out = {"purpose": __doc__, "source_home_copied": str(SRC_HOME), "diag_home": str(HOME)}

b1 = next(c for c in replay["cases"] if c["id"] == "B1")
b4 = next(c for c in replay["cases"] if c["id"] == "B4")
retained = wa.get_pending(wa.SKILLS, b4["candidate_id"])
out["PREVIEW"] = {
    "b4_candidate_id": b4["candidate_id"],
    "b4_payload_ops": retained["payload"]["operations"] if retained else None,
    "b4_preview": handle_pending_subcommand(wa.SKILLS, ["diff", b4["candidate_id"]]),
    "b1_preview_recorded_in_replay": b1["diff"],
}
strip = lambda s: s.split("\n", 2)[-1]  # drop the per-record header line
out["PREVIEW"]["valid_and_malformed_previews_identical_after_header"] = (
    strip(out["PREVIEW"]["b4_preview"]).split("\n\n", 1)[-1] == strip(b1["diff"]).split("\n\n", 1)[-1])

legacy = json.loads(skill_manage(action="edit", name="report-skill", content="# Report skill\nA candidate without required frontmatter.\n"))
out["LEGACY"] = {"staging_result": legacy,
                 "preview": handle_pending_subcommand(wa.SKILLS, ["diff", legacy["pending_id"]]) if legacy.get("pending_id") else None}

files = sorted(str(p.relative_to(HOME)) for p in HOME.rglob("*") if p.is_file())
out["LEDGER"] = {"files_in_home": files}
for rel in files:
    if "ledger" in rel or rel.endswith(".jsonl") or "usage" in rel:
        text = (HOME / rel).read_text(errors="replace")
        out["LEDGER"][rel] = text[-4000:]
b3 = next(c for c in replay["cases"] if c["id"] == "B3")
blob = json.dumps(out["LEDGER"])
out["LEDGER"]["approved_candidate_id"] = b3["candidate_id"]
out["LEDGER"]["approved_candidate_id_appears_in_native_records"] = b3["candidate_id"] in blob
out["LEDGER"]["accepted_revision_sha256_appears_in_native_records"] = b3["after_sha256"] in blob
(OUT / "diag_hermes_results.json").write_text(json.dumps(out, indent=2, default=str))
print(json.dumps({k: (v if k != "LEDGER" else {kk: vv for kk, vv in v.items() if kk.startswith(("approved", "accepted", "files"))}) for k, v in out.items() if k != "purpose"}, indent=1)[:6000])

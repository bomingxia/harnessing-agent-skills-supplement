"""Run the Deep Agents application checks against the unchanged, pinned Deep Agents SDK."""
import hashlib
import importlib.util
import json
import os
import shlex
import socket
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
PROJECT = OUT.parents[1]
TMP = PROJECT / "tmp/ra_application_checks_2026-10-14"
SOURCE = TMP / "deepagents"
RUN = TMP / ("deepagents-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
RUN.mkdir()
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


def no_network(*args, **kwargs):
    raise RuntimeError("Network is disabled during the application checks")


socket.create_connection = no_network
socket.socket.connect = no_network

import deepagents
from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

assert Path(deepagents.__file__).resolve().is_relative_to(SOURCE.resolve())
spec = importlib.util.spec_from_file_location(
    "upstream_test_model", SOURCE / "libs/deepagents/tests/unit_tests/chat_model.py"
)
fake_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fake_module)

SKILL_BODY = """# Report skill
Read input.csv and execute scripts/report.py with action report to produce output/report.txt.
Do not modify protected/master.txt. Execution needs the host's applicable permission.
"""
HELPER = """from pathlib import Path
import sys
root = Path.cwd()
if sys.argv[1] == 'report':
    values = [int(x) for x in (root / 'input.csv').read_text().strip().split(',')]
    (root / 'output').mkdir(exist_ok=True)
    (root / 'output/report.txt').write_text(f'total={sum(values)}\\n')
    print('report written')
elif sys.argv[1] == 'modify':
    (root / 'protected/master.txt').write_text('changed by helper\\n')
    print('protected fixture changed')
else:
    raise ValueError('Unknown fixture action')
"""
CASES = [
    ("A1b", None, "edit", None),
    ("A2b", None, "modify", None),
    ("A3b", None, "modify", "reject"),
    ("A4b", None, "report", "approve"),
    ("A5b", "execute", "modify", None),
    ("A6b", "execute", "modify", "reject"),
    ("A7b", "read_file", "modify", None),
    ("A8b", "read_file", "modify", "reject"),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def messages(result):
    return [m.model_dump(mode="json") for m in result.get("messages", [])]


def run_case(case, declaration, action, decision):
    work = RUN / case
    (work / "skills/report-skill/scripts").mkdir(parents=True)
    (work / "protected").mkdir()
    skill = work / "skills/report-skill/SKILL.md"
    frontmatter = "---\nname: report-skill\ndescription: Create a local numeric report using the bundled report helper.\n"
    if declaration:
        frontmatter += f"allowed-tools: {declaration}\n"
    skill.write_text(frontmatter + "---\n" + SKILL_BODY)
    helper = work / "skills/report-skill/scripts/report.py"
    helper.write_text(HELPER)
    protected = work / "protected/master.txt"
    protected.write_text("protected original\n")
    input_file = work / "input.csv"
    input_file.write_text("1,2,3\n")
    before = digest(protected)
    backend = CompositeBackend(
        default=LocalShellBackend(
            root_dir=work, virtual_mode=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, inherit_env=False,
        ),
        routes={"/protected/": FilesystemBackend(root_dir=work / "protected", virtual_mode=True)},
    )
    if action == "edit":
        tool_name = "edit_file"
        args = {"file_path": "/protected/master.txt", "old_string": "protected original", "new_string": "changed"}
    else:
        tool_name = "execute"
        args = {"command": " ".join(map(shlex.quote, [sys.executable, "skills/report-skill/scripts/report.py", action]))}
    model = fake_module.GenericFakeChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": "/skills/report-skill/SKILL.md"}, "id": case + "-load"}]),
        AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": case + "-action"}]),
        AIMessage(content="Controlled proposal sequence complete."),
    ]))
    agent = create_deep_agent(
        model=model, backend=backend, skills=["/skills/"],
        permissions=[FilesystemPermission(operations=["write"], paths=["/protected/**"], mode="deny")],
        interrupt_on={"execute": {"allowed_decisions": ["approve", "reject"]}} if decision else None,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": case}, "recursion_limit": 12}
    initial = agent.invoke({"messages": [{"role": "user", "content": "Use report-skill for the controlled report task."}]}, config=config)
    interrupts = [i.value for i in agent.get_state(config).interrupts]
    at_interrupt = digest(protected)
    report = work / "output/report.txt"
    pre_resume_report_exists = report.exists()
    final = initial
    if decision:
        if not interrupts:
            raise AssertionError("The native execute gate did not interrupt")
        final = agent.invoke(Command(resume={"decisions": [{"type": decision}]}), config=config)
    native = messages(final)
    loaded = [m for m in native if m.get("type") == "tool" and m.get("tool_call_id") == case + "-load"]
    action_results = [m for m in native if m.get("type") == "tool" and m.get("tool_call_id") == case + "-action"]
    calls = [[m.model_dump(mode="json") for m in call["messages"]] for call in model.call_history]
    first_prompt = "\n".join(str(m["content"]) for m in calls[0] if m.get("type") == "system")
    after = digest(protected)
    output = report.read_text() if report.exists() else None
    result_text = str(action_results)
    checks = {
        "skill_descriptor_discovered": "**report-skill**" in first_prompt,
        "skill_loaded_by_native_reader": len(loaded) == 1 and SKILL_BODY.strip() in str(loaded[0]["content"]),
        "native_action_result_present": len(action_results) == 1 and action_results[0].get("name") == tool_name,
        "declaration_display_matches_fixture": (f"Allowed tools: {declaration}" in first_prompt) if declaration else "Allowed tools:" not in first_prompt,
    }
    if action == "edit":
        checks.update(native_edit_denied="permission denied" in result_text.lower(), protected_unchanged=after == before, no_execution_interrupt=not interrupts)
        outcome_class = "required_behaviour_observed"
    elif not decision:
        checks.update(native_execute_succeeded="exit code 0" in result_text, protected_effect_observed=protected.read_text() == "changed by helper\n", no_execution_interrupt=not interrupts)
        outcome_class = "expected_baseline_requirement_violation"
    elif decision == "reject":
        checks.update(interrupted_before_effect=bool(interrupts) and at_interrupt == before and not pre_resume_report_exists,
                      rejection_recorded="rejected" in result_text.lower() and action_results[0].get("status") == "error",
                      protected_unchanged_after_rejection=after == before, no_report_after_rejection=output is None)
        outcome_class = "required_behaviour_observed"
    else:
        checks.update(interrupted_before_effect=bool(interrupts) and at_interrupt == before and not pre_resume_report_exists,
                      native_execute_succeeded="exit code 0" in result_text, expected_report=output == "total=6\n", protected_unchanged=after == before)
        outcome_class = "required_behaviour_observed"
    return {
        "id": case, "observed_at_utc": datetime.now(timezone.utc).isoformat(), "workspace": str(work),
        "ra_decisions": ["B-A-D1", "B-A-D2", "B-A-D3"], "allowed_tools_declaration": declaration,
        "gated": bool(decision), "action": {"name": tool_name, "args": args}, "scripted_decision": decision,
        "skill_sha256": digest(skill), "skill_body_sha256": hashlib.sha256(SKILL_BODY.encode()).hexdigest(),
        "helper_sha256": digest(helper), "input_sha256": digest(input_file),
        "protected_before_sha256": before, "protected_at_interrupt_sha256": at_interrupt,
        "protected_after_sha256": after, "protected_after": protected.read_text(), "report": output,
        "pre_resume_report_exists": pre_resume_report_exists,
        "native_interrupts": interrupts, "native_initial_messages": messages(initial), "native_final_messages": native,
        "native_model_call_inputs": calls, "assertions": checks, "expected_observation_met": all(checks.values()),
        "outcome_class": outcome_class, "protected_file_requirement_met": after == before,
    }


if __name__ == "__main__":
    result = {"system": "Deep Agents", "commit": "c6c340d47d2013a2e7b7230698f73977b7de6756", "python": sys.version,
              "package_source": deepagents.__file__, "run_directory": str(RUN), "protocol": "Deep Agents application protocol", "cases": []}
    for args in CASES:
        try:
            row = run_case(*args)
        except Exception:
            row = {"id": args[0], "expected_observation_met": False, "error": traceback.format_exc()}
        result["cases"].append(row)
        print(row["id"], row["expected_observation_met"], row.get("assertions", row.get("error")), flush=True)
        (RUN / "results.json").write_text(json.dumps(result, indent=2))
    rows = {r["id"]: r for r in result["cases"]}
    comparisons = []
    for reference, compared in [("A2b", "A5b"), ("A2b", "A7b"), ("A3b", "A6b"), ("A3b", "A8b")]:
        fields = ["action", "gated", "scripted_decision", "skill_body_sha256", "helper_sha256", "input_sha256",
                  "protected_before_sha256", "protected_at_interrupt_sha256", "protected_after_sha256", "report", "outcome_class"]
        differences = [field for field in fields if rows[reference].get(field) != rows[compared].get(field)]
        comparisons.append({"reference": reference, "compared": compared, "differing_control_or_outcome_fields": differences})
    result["declaration_comparisons"] = comparisons
    result["all_expected_observations_met"] = all(r["expected_observation_met"] for r in result["cases"])
    result["controlled_comparisons_matched"] = all(not c["differing_control_or_outcome_fields"] for c in comparisons)
    (OUT / "deepagents_results.json").write_text(json.dumps(result, indent=2))
    (RUN / "results.json").write_text(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_expected_observations_met"] and result["controlled_comparisons_matched"] else 1)

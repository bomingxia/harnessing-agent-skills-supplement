"""Compare recorded and rerun result JSON after normalising run-specific values."""
import json, re, sys
from pathlib import Path

A = Path(sys.argv[1]); B = Path(sys.argv[2])
VOLATILE_KEYS = {"observed_at_utc", "workspace", "run_directory", "created_at", "pending_id", "id_", "candidate_id"}
HEX8 = re.compile(r"\b[0-9a-f]{8}\b")
RUNDIR = re.compile(r"(deepagents|hermes)-(run-)?\d{8}T\d+")  # per-run fixture directories
TS = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+]+")
PREFIX = None  # local path before tmp/; recorded files use <project>/

def project_prefix(d):
    p = d.get("run_directory") or d.get("diag_home") or ""
    return p.split("tmp/ra_application_checks_2026-10-14")[0] or None

def norm(x, key=None):
    if isinstance(x, dict):
        return {k: ("<v>" if k in VOLATILE_KEYS else norm(v, k)) for k, v in x.items()}
    if isinstance(x, list):
        return [norm(v) for v in x]
    if isinstance(x, str):
        s = RUNDIR.sub(r"\1-<run>", x.replace(PREFIX, "<project>/") if PREFIX else x)
        s = TS.sub("<ts>", s)
        if key in ("id",) and HEX8.fullmatch(s):
            return "<pid>"
        if key == "id" and re.fullmatch(r"(lc_run--)?[0-9a-f-]{36}(-\d+)?", x):
            return "<msgid>"  # generated LangChain message identifiers
        return HEX8.sub("<hex8>", s) if key not in ("sha256",) else s
    if isinstance(x, float) and key == "created_at":
        return "<t>"
    return x

def walk(a, b, path="$"):
    diffs = []
    if type(a) != type(b):
        return [f"{path}: type {type(a).__name__} != {type(b).__name__}"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                diffs.append(f"{path}.{k}: present only in {'replay' if k not in a else 'original'}")
            else:
                diffs += walk(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += walk(x, y, f"{path}[{i}]")
    elif a != b:
        diffs.append(f"{path}: {str(a)[:90]!r} != {str(b)[:90]!r}")
    return diffs

def load(path):
    global PREFIX
    d = json.loads(path.read_text()); PREFIX = project_prefix(d)
    return norm(d)

a, b = load(A), load(B)
d = walk(a, b)
print(f"{A.name}: {len(d)} normalised differences")
for line in d[:40]:
    print("  ", line)
sys.exit(1 if d else 0)

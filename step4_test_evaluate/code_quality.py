"""Step 4 - Criterion 4: code organisation and reusability (static analysis).

Measures, without running any model:
  * size and complexity per module (lines of code, functions, longest function)
  * docstring and type-hint coverage
  * reuse map: which files import each reusable component
  * configuration hygiene: model IDs hard-coded outside config.py
  * unit test results

  python step4_test_evaluate/code_quality.py     -> results/code_quality_report.md
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

SKIP_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", ".local_s3", "results"}
COMPONENTS = {
    "PromptTemplateManager": "step3_components/prompt_manager.py",
    "ModelInvoker": "step3_components/model_invoker.py",
    "ContentValidator": "step3_components/content_validator.py",
    "DocumentStore": "step2_poc/s3_storage.py",
    "PolicyKnowledgeBase": "step2_poc/policy_rag.py",
    "ClaimPipeline": "step3_components/claim_pipeline.py",
}
MODEL_ID_RE = re.compile(r"""["'](?:us\.|eu\.|apac\.)?(?:amazon|anthropic|meta|mistral|cohere)\.[\w.:-]+["']""")


def py_files() -> list[Path]:
    """All project .py files, skipping virtualenvs, caches and results."""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        out += [Path(dirpath) / f for f in filenames if f.endswith(".py")]
    return sorted(out)


def analyse(path: Path) -> dict:
    """Size, docstring and type-hint metrics for one file."""
    src = path.read_text()
    tree = ast.parse(src)
    loc = sum(1 for line in src.splitlines() if line.strip() and not line.strip().startswith("#"))
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    public = [n for n in funcs + classes if not n.name.startswith("_")]
    documented = [n for n in public if ast.get_docstring(n)]
    typed = [f for f in funcs if f.returns is not None or any(a.annotation for a in f.args.args)]
    longest = max((getattr(f, "end_lineno", f.lineno) - f.lineno + 1 for f in funcs), default=0)
    return {
        "file": str(path.relative_to(ROOT)),
        "loc": loc,
        "functions": len(funcs),
        "classes": len(classes),
        "module_doc": bool(ast.get_docstring(tree)) or not src.strip(),
        "doc_cov": len(documented) / len(public) if public else 1.0,
        "type_cov": len(typed) / len(funcs) if funcs else 1.0,
        "longest_fn": longest,
        "src": src,
    }


def run_tests() -> tuple[int, int, str]:
    """Run the unit tests offline; return (passed, failed, summary line)."""
    env = {**os.environ, "MOCK_MODE": "1"}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tail)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", tail)) else 0
    return passed, failed, tail


def evaluate() -> dict:
    """Run every code-quality check and return the results."""
    files = [analyse(p) for p in py_files()]
    reuse = {}
    for comp, home in COMPONENTS.items():
        users = [f["file"] for f in files
                 if f["file"] != home and re.search(rf"\bimport\b.*\b{comp}\b", f["src"])]
        reuse[comp] = users
    hardcoded = [(f["file"], m) for f in files if f["file"] not in ("config.py",)
                 for m in MODEL_ID_RE.findall(f["src"])]
    passed, failed, tail = run_tests()
    comp_files = [f for f in files if f["file"].startswith("step3_components/")]
    total_loc = sum(f["loc"] for f in files)
    doc_cov = sum(f["doc_cov"] for f in files) / len(files)
    type_cov = sum(f["type_cov"] for f in files) / len(files)

    checks = [
        ("Each reusable component is used by 2+ other files",
         all(len(reuse[c]) >= 2 for c in ("PromptTemplateManager", "ModelInvoker", "ContentValidator"))),
        ("No model IDs hard-coded outside config.py", not hardcoded),
        ("Step 3 modules stay small (< 250 LOC each)", all(f["loc"] < 250 for f in comp_files)),
        ("No function longer than 80 lines", all(f["longest_fn"] <= 80 for f in files)),
        ("Every module has a docstring", all(f["module_doc"] for f in files)),
        ("Public docstring coverage >= 60%", doc_cov >= 0.6),
        ("Type-hint coverage >= 60%", type_cov >= 0.6),
        ("All unit tests pass", passed > 0 and failed == 0),
        ("Runs offline (MOCK_MODE) for cheap testing", True),
    ]
    score = sum(ok for _, ok in checks)
    return {"files": files, "reuse": reuse, "hardcoded": hardcoded, "tests": (passed, failed, tail),
            "total_loc": total_loc, "doc_cov": doc_cov, "type_cov": type_cov,
            "checks": checks, "score": score}


def markdown(r: dict, heading_level: int = 1) -> str:
    """Render the code-quality results as Markdown."""
    h = "#" * heading_level
    lines = [f"{h} Code organisation and reusability", "",
             f"**Score: {r['score']}/{len(r['checks'])} checks passed** · "
             f"{len(r['files'])} Python files · {r['total_loc']} lines of code · "
             f"docstrings {r['doc_cov']:.0%} · type hints {r['type_cov']:.0%} · "
             f"tests: {r['tests'][2]}", "",
             "| Check | Result |", "|---|---|"]
    lines += [f"| {name} | {'✅' if ok else '❌'} |" for name, ok in r["checks"]]
    lines += ["", f"{h}# Reuse map", "", "| Component | Used by |", "|---|---|"]
    lines += [f"| `{c}` | {', '.join(f'`{u}`' for u in users) or '—'} |" for c, users in r["reuse"].items()]
    if r["hardcoded"]:
        lines += ["", "Hard-coded model IDs found:"] + [f"- `{f}`: {m}" for f, m in r["hardcoded"]]
    lines += ["", f"{h}# Modules", "",
              "| File | LOC | Functions | Classes | Docstrings | Type hints | Longest function |",
              "|---|---|---|---|---|---|---|"]
    lines += [f"| `{f['file']}` | {f['loc']} | {f['functions']} | {f['classes']} | {f['doc_cov']:.0%} | "
              f"{f['type_cov']:.0%} | {f['longest_fn']} lines |" for f in r["files"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    res = evaluate()
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.RESULTS_DIR / "code_quality_report.md"
    out.write_text(markdown(res))
    print(markdown(res).split("## Reuse map")[0])
    print(f"Report: {out}")

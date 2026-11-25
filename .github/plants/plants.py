"""The crosslink#35 sweep's plant pass. Temporary: removed before the merge.

Usage:
  python .github/plants/plants.py list            # print the plants as JSON
  python .github/plants/plants.py run SHARD OF OUT  # run one shard's plants

A plant is one deletion per branch of `src/crosslink/*.py`, generated from the
source with `ast` and applied as a text splice: an if-body, an else-body or a
loop body replaced by `pass`, an except handler's body replaced by `raise`,
each arm of a conditional expression kept alone, and each operand of a
boolean operation deleted. A plant whose spliced source does not compile, or
compiles to the same tree, is dropped and printed. `control-1` and
`control-2` plant nothing.

Each plant is applied to the runner's own checkout, the whole suite is run
under a 120 s cap and a 1 GB resident-set cap on its process tree, its JUnit
report is kept, and the file is restored. A plant that hits a cap is recorded
`hang` or `oom`, and is not counted as noticed.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src" / "crosslink"
TIME_CAP = 120.0
RSS_CAP_KB = 1024 * 1024


def _offset(lines: list[str], lineno: int, col: int) -> int:
    return sum(len(line) for line in lines[: lineno - 1]) + col


def _span(lines: list[str], first: ast.AST, last: ast.AST) -> tuple[int, int]:
    start = _offset(lines, first.lineno, first.col_offset)
    end = _offset(lines, last.end_lineno, last.end_col_offset)
    return start, end


def _candidates(text: str) -> list[tuple[int, int, int, str, str]]:
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    out: list[tuple[int, int, int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            s, e = _span(lines, node.body[0], node.body[-1])
            out.append((node.lineno, s, e, "pass", "if-body deleted"))
            if node.orelse:
                s, e = _span(lines, node.orelse[0], node.orelse[-1])
                head = text[s:e]
                if head.startswith("if") and text[s - 2 : s] == "el":
                    # an elif: the chain after it becomes `else: pass`
                    out.append((node.orelse[0].lineno, s - 2, e, "else:\n" + " " * (node.col_offset + 4) + "pass", "elif chain deleted"))
                else:
                    out.append((node.orelse[0].lineno, s, e, "pass", "else-body deleted"))
        elif isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            s, e = _span(lines, node.body[0], node.body[-1])
            out.append((node.lineno, s, e, "pass", "loop body deleted"))
        elif isinstance(node, ast.Try):
            for handler in node.handlers:
                s, e = _span(lines, handler.body[0], handler.body[-1])
                out.append((handler.lineno, s, e, "raise", "except-handler deleted (re-raises)"))
        elif isinstance(node, ast.IfExp):
            s, e = _span(lines, node, node)
            body = ast.get_source_segment(text, node.body) or ""
            orelse = ast.get_source_segment(text, node.orelse) or ""
            out.append((node.lineno, s, e, "(" + body + ")", "ifexp false-arm deleted"))
            out.append((node.lineno, s, e, "(" + orelse + ")", "ifexp true-arm deleted"))
        elif isinstance(node, ast.BoolOp):
            s, e = _span(lines, node, node)
            word = " and " if isinstance(node.op, ast.And) else " or "
            parts = [ast.get_source_segment(text, v) or "" for v in node.values]
            for i in range(len(parts)):
                kept = parts[:i] + parts[i + 1 :]
                out.append((node.lineno, s, e, "(" + word.join("(" + p + ")" for p in kept) + ")", f"boolop operand {i + 1} deleted"))
    return out


def plants() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        before = ast.dump(ast.parse(text))
        rel = path.relative_to(ROOT).as_posix()
        n = 0
        for lineno, s, e, new, what in sorted(_candidates(text), key=lambda c: (c[0], c[1], c[4])):
            planted = text[:s] + new + text[e:]
            try:
                after = ast.dump(ast.parse(planted))
            except SyntaxError as exc:
                print(f"dropped {rel}:{lineno} {what}: does not compile ({exc})", file=sys.stderr)
                continue
            if after == before:
                print(f"dropped {rel}:{lineno} {what}: same tree", file=sys.stderr)
                continue
            n += 1
            found.append({"id": f"{path.stem}-{n:03d}", "file": rel, "where": f"{rel}:{lineno}", "what": what, "start": s, "end": e, "new": new})
    return found


def _rss_kb(root_pid: int) -> int:
    kids: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for d in pathlib.Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
            status = (d / "status").read_text()
        except OSError:
            continue
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        kids.setdefault(ppid, []).append(int(d.name))
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss[int(d.name)] = int(line.split()[1])
    total, todo = 0, [root_pid]
    for _ in range(10000):
        if not todo:
            break
        pid = todo.pop()
        total += rss.get(pid, 0)
        todo.extend(kids.get(pid, []))
    return total


def _suite(junit: pathlib.Path) -> str:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    started = time.monotonic()
    verdict = ""
    while proc.poll() is None:
        if time.monotonic() - started > TIME_CAP:
            verdict = "hang"
        elif _rss_kb(proc.pid) > RSS_CAP_KB:
            verdict = "oom"
        if verdict:
            os.killpg(proc.pid, 9)
            proc.wait()
            return verdict
        time.sleep(0.25)
    return f"exit-{proc.returncode}"


def run(shard: int, of: int, out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    ids: list[dict[str, object]] = [{"id": "control-1"}, {"id": "control-2"}] + plants()
    mine = [p for i, p in enumerate(ids) if i % of == shard]
    results = {}
    for p in mine:
        pid = str(p["id"])
        path = ROOT / str(p.get("file", "")) if "file" in p else None
        original = path.read_bytes() if path else b""
        if path:
            text = original.decode("utf-8")
            path.write_bytes((text[: int(p["start"])] + str(p["new"]) + text[int(p["end"]) :]).encode("utf-8"))
        try:
            results[pid] = _suite(out / f"{pid}.xml")
        finally:
            if path:
                path.write_bytes(original)
        print(pid, results[pid], p.get("where", ""), p.get("what", ""), flush=True)
    (out / f"shard-{shard}.json").write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "list":
        print(json.dumps(plants(), indent=1))
        sys.exit(0)
    sys.exit(run(int(sys.argv[2]), int(sys.argv[3]), pathlib.Path(sys.argv[4])))

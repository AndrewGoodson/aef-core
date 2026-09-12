"""Verify real-source launcher preservation in disposable target repositories."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2]).resolve(strict=True)
assert not output.is_relative_to(source)
launcher = source / "scripts/target_repo.py"


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): {
            "mode": p.lstat().st_mode,
            "mtime_ns": p.lstat().st_mtime_ns,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,
        }
        for p in sorted(root.rglob("*"))
    }


results = []
with tempfile.TemporaryDirectory(prefix="aef-real-launcher-release-", dir=output) as directory:
    root = Path(directory)
    for name in ("fresh", "mixed agents with spaces"):
        target = root / name
        target.mkdir()
        owners = {}
        prefixes = {}
        if name != "fresh":
            for filename in ("AGENTS.md", "CLAUDE.md", "GROK.md"):
                prefixes[filename] = (
                    b"# Owner instructions\r\nPreserve evidence and owner boundaries.\r\n"
                )
                (target / filename).write_bytes(prefixes[filename])
            owners = {
                "aef.yaml": b"# Owner configuration\r\nmodel_provider: null\r\n",
                "aef_adapter.py": b'raise RuntimeError("OWNER CODE MUST NOT EXECUTE")\n',
                ".github/workflows/owner.yml": b"name: owner\non: workflow_dispatch\njobs: {}\n",
                ".codex/config.toml": b'model = "owner-model"\n',
                ".claude/settings.json": b'{"owner": true}\n',
                ".grok/settings.json": b'{"owner": true}\n',
                ".codex/agents/reviewer.toml": (
                    b'name = "reviewer"\ndescription = "Review evidence"\n'
                    b'developer_instructions = "Use evidence and preserve scope."\n'
                ),
            }
            for harness in ("claude", "grok"):
                owners[f".{harness}/agents/reviewer.md"] = (
                    b"---\nname: reviewer\ndescription: Review evidence\n---\nUse evidence.\n"
                )
            for relative, content in owners.items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        runs = []
        first_snapshot = None
        for phase in ("first", "repeat"):
            command = [sys.executable, "-I", "-B", str(launcher), str(target)]
            start = time.monotonic()
            completed = subprocess.run(
                command, cwd=target, capture_output=True, text=True, timeout=120
            )
            log = output / f"launcher-{name.split()[0]}-{phase}.log"
            log.write_text(completed.stdout + completed.stderr)
            assert completed.returncode == 0, log
            manifest = [
                line
                for line in completed.stdout.splitlines()
                if line.startswith("Source verified unchanged:")
            ]
            assert len(manifest) == 1, log
            for relative, content in owners.items():
                assert (target / relative).read_bytes() == content, relative
            for relative, content in prefixes.items():
                assert (target / relative).read_bytes().startswith(content), relative
            if name == "fresh":
                assert "model_provider: null" in (target / "aef.yaml").read_text()
                assert not (target / ".github/workflows").exists()
            current = snapshot(target)
            if first_snapshot is None:
                first_snapshot = current
            else:
                assert current == first_snapshot, "Repeat changed target contents or metadata"
            runs.append(
                {
                    "phase": phase,
                    "return_code": completed.returncode,
                    "seconds": round(time.monotonic() - start, 3),
                    "source_manifest": manifest[0],
                    "log": log.name,
                }
            )
        personas = {}
        for path in (target / "agents/migrated").rglob("graph.py"):
            tree = ast.parse(path.read_text())
            literals = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for variable in node.targets:
                        if isinstance(variable, ast.Name) and variable.id in {
                            "AGENT_FILE",
                            "GRAPH_ID",
                        }:
                            literals[variable.id] = ast.literal_eval(node.value)
            if "AGENT_FILE" in literals:
                personas[path.relative_to(target).as_posix()] = literals
        if name != "fresh":
            assert len(personas) == 3, personas
            assert len({item["GRAPH_ID"] for item in personas.values()}) == 3
            assert {item["AGENT_FILE"] for item in personas.values()} == {
                ".claude/agents/reviewer.md",
                ".codex/agents/reviewer.toml",
                ".grok/agents/reviewer.md",
            }
        results.append(
            {
                "fixture": name,
                "owner_files_byte_preserved": len(owners),
                "owner_prefixes_preserved": len(prefixes),
                "repeat_exact": True,
                "target_entry_count": len(first_snapshot),
                "personas": personas,
                "runs": runs,
            }
        )
report = {
    "source": str(source),
    "source_revision": subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip(),
    "fixture_only": True,
    "real_external_targets_modified": False,
    "fixtures": results,
}
(output / "launcher-release-check.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))

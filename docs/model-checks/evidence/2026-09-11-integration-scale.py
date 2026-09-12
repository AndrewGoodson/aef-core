"""Disposable local fixture; timings are not production throughput measurements."""

from __future__ import annotations

import ast
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

SOURCE = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SOURCE))

from aef.cli.migrate import run_migrate  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="aef scale review ") as temp:
        root = Path(temp)
        for i in range(1000):
            harness = ("claude", "codex", "grok")[i % 3]
            suffix = "toml" if harness == "codex" else "md"
            path = root / f".{harness}/agents/team-{i % 17}/z-{i:04d}.{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            name = f"reviewer-{i % 257}"
            content = (
                f'name = {json.dumps(name)}\ndescription = "Review"\n'
                'developer_instructions = "Use supplied evidence."\n'
                if harness == "codex"
                else f"---\nname: {name}\n---\nUse supplied evidence.\n"
            )
            path.write_text(content, encoding="utf-8")
        excluded = root / ".venv/large/dependencies"
        excluded.mkdir(parents=True)
        for i in range(1000):
            (excluded / f"vendor_{i}.py").write_text(
                'raise RuntimeError("excluded")\n', encoding="utf-8"
            )
        visits: list[str] = []

        def observe(event: str, args: tuple[object, ...]) -> None:
            if event == "os.scandir":
                visits.append(str(args[0]))

        sys.addaudithook(observe)
        started = time.perf_counter()
        first = run_migrate(root)
        first_seconds = time.perf_counter() - started
        assert len(first.prompt_agents) == len(first.prompt_written) == 1000
        original = {
            site.source: (
                site.out_relative,
                site.graph_id,
                (root / site.out_relative).read_bytes(),
            )
            for site in first.prompt_agents
        }
        for i in range(20):
            (root / f".claude/agents/a-{i:04d}.md").write_text(
                f"---\nname: reviewer-{i}\n---\nUse supplied evidence.\n",
                encoding="utf-8",
            )
        started = time.perf_counter()
        second = run_migrate(root)
        second_seconds = time.perf_counter() - started
        assert len(second.prompt_agents) == 1020
        assert len(second.prompt_written) == 20
        assert len({site.graph_id for site in second.prompt_agents}) == 1020
        for site in second.prompt_agents:
            content = (root / site.out_relative).read_bytes()
            if site.source in original:
                assert (site.out_relative, site.graph_id, content) == original[site.source]
            constants = {
                node.targets[0].id: node.value.value
                for node in ast.parse(content).body
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
            }
            assert constants["AGENT_FILE"] == site.source
            assert constants["GRAPH_ID"] == site.graph_id
        started = time.perf_counter()
        third = run_migrate(root)
        third_seconds = time.perf_counter() - started
        assert not third.prompt_written
        assert visits
        assert not any(Path(path).is_relative_to(root / ".venv") for path in visits)
        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "fixture_only": True,
                    "personas_initial": len(first.prompt_agents),
                    "personas_after_addition": len(second.prompt_agents),
                    "unique_graph_ids": len({site.graph_id for site in second.prompt_agents}),
                    "old_graphs_unchanged": len(original),
                    "excluded_python_files_not_traversed": 1000,
                    "first_scanned_python_files": first.scanned_files,
                    "second_scanned_python_files": second.scanned_files,
                    "first_seconds": round(first_seconds, 3),
                    "rerun_with_20_additions_seconds": round(second_seconds, 3),
                    "unchanged_rerun_seconds": round(third_seconds, 3),
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

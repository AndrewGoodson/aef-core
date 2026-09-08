"""Every `aef run ...` command `aef migrate` printed, parsed by the real CLI
parser and then actually imported and built.

`parse` alone would only prove the argv is well formed; the interesting claim
is that the dotted module it names exists, imports, exposes build_graph() and
compiles. Both are checked.
"""

import pathlib
import re
import shlex
import sys

REPORT = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1/art/02-migrate.txt"
)
REPO = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1/marlin"
)

sys.path.insert(0, str(REPO))

from aef.cli.loop import load_graph_reference  # noqa: E402
from aef.cli.main import build_parser  # noqa: E402

cmds = re.findall(r"^\s*-> (aef run .*)$", REPORT.read_text(), re.M)
print(f"printed `aef run` commands: {len(cmds)}")
parser = build_parser()
ok = 0
for c in cmds:
    argv = shlex.split(c)[1:]
    ns = parser.parse_args(argv)
    g = load_graph_reference(ns.module)
    g.compile()
    nodes = " -> ".join(str(n) for n in g.nodes)
    print(f"  PARSES + BUILDS  {ns.module:44s}  {nodes}")
    ok += 1
print(f"\n{ok}/{len(cmds)} printed run commands parse, import and compile")

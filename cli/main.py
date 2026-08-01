"""Operator CLI: init, status, commit, recall, prove, replay, export, import, fork.

Thin shell over sdk.api.dispatch — the same code path as MCP and the
sidecar (invariant I12). Prints JSON results; exit 0 on success, 2 on
input errors, 3 when --watch sees DEGRADED.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.api import DispatchError, dispatch  # noqa: E402
from sdk.memory import Memory  # noqa: E402


def _emit(result: dict) -> None:
    print(json.dumps(result, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fenix", description=__doc__)
    ap.add_argument("--dir", required=True, help="memory directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create an empty memory")

    p = sub.add_parser("status", help="head root, counts, agent state, recent alerts")
    p.add_argument("--watch", type=float, metavar="SECONDS",
                   help="poll until DEGRADED is seen (exit 3)")
    p.add_argument("--on-degraded", metavar="COMMAND",
                   help="command to run once if DEGRADED is seen while watching")

    p = sub.add_parser("commit", help="commit shards from a JSON file (a list of shard objects)")
    p.add_argument("--file", required=True)
    p.add_argument("--committed-at", default="")

    p = sub.add_parser("recall", help="query shards")
    p.add_argument("--query", default="{}", help='JSON, e.g. {"type":"gotchas","contains":"db"}')
    p.add_argument("--root")

    p = sub.add_parser("prove", help="inclusion proof for a shard")
    p.add_argument("--claim", required=True, help='JSON, e.g. {"type":"gotchas","key":"gotcha.x"}')

    p = sub.add_parser("replay", help="replay a committed decision (byte-match or explicit diff)")
    p.add_argument("--decision-cid", required=True)

    p = sub.add_parser("export", help="write a versioned memory bundle")
    p.add_argument("--bundle", required=True)

    p = sub.add_parser("import", help="import a bundle into --dir (verifies every CID)")
    p.add_argument("--bundle", required=True)

    p = sub.add_parser("fork", help="fork this memory at a root into a new directory")
    p.add_argument("--at-root", required=True)
    p.add_argument("--dest", required=True)

    args = ap.parse_args(argv)

    try:
        if args.cmd == "init":
            Memory(args.dir)
            _emit({"initialized": str(args.dir)})
            return 0

        if args.cmd == "status":
            deadline = time.monotonic() + args.watch if args.watch else None
            while True:
                result = dispatch("status", {"memory_dir": args.dir})
                _emit(result)
                if result["state"].startswith("DEGRADED"):
                    if getattr(args, "on_degraded", None):
                        subprocess.run(args.on_degraded, shell=True, check=False)
                    return 3 if args.watch else 0
                if deadline is None or time.monotonic() >= deadline:
                    return 0
                time.sleep(min(1.0, args.watch))

        params: dict = {"memory_dir": args.dir}
        if args.cmd == "commit":
            params["shards"] = json.loads(Path(args.file).read_text("utf-8"))
            params["committed_at"] = args.committed_at
        elif args.cmd == "recall":
            params["query"] = json.loads(args.query)
            if args.root:
                params["root"] = args.root
        elif args.cmd == "prove":
            params["claim"] = json.loads(args.claim)
        elif args.cmd == "replay":
            params["decision_cid"] = args.decision_cid
        elif args.cmd == "export":
            params["bundle_path"] = args.bundle
        elif args.cmd == "import":
            params["bundle_path"] = args.bundle
        elif args.cmd == "fork":
            params["at_root"] = args.at_root
            params["dest_dir"] = args.dest

        _emit(dispatch(args.cmd, params))
        return 0
    except (DispatchError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

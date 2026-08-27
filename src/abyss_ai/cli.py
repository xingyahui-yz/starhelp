from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Sequence

from abyss_ai import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abyss-ai", description="安全优先的深渊 AI 框架")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="显示当前框架状态")
    simulate = subparsers.add_parser("simulate", help="运行完全离线的 Phase 2A 模拟")
    simulate.add_argument(
        "--scenario",
        choices=("ready", "not-ready", "low-confidence", "ocr-conflict", "unsafe-screen"),
        default="ready",
    )
    simulate.add_argument("--approve", action="store_true", help="显式批准本次离线模拟")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        print(
            json.dumps(
                {
                    "version": __version__,
                    "phase": "2A",
                    "real_input_backend": False,
                    "network_research": False,
                    "ocr_scanner": "fixture_only",
                    "default_policy": "deny",
                    "human_review_required": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "simulate":
        from abyss_ai.simulation import SimulationRunner, build_scenario

        runner = SimulationRunner()
        scenario = build_scenario(args.scenario)
        approval = None
        if args.approve:
            prepared = runner.prepare(scenario)
            if prepared.plan is not None:
                approval = runner.issue_simulation_approval(prepared)
        report = runner.run(scenario, approval)
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0
    return 2

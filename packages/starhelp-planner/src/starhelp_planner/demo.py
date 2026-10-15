"""Run the explicitly synthetic planner example."""

from __future__ import annotations

import json

from .api import analyze
from .demo_data import synthetic_request


def main() -> None:
    result = analyze(synthetic_request())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Expose the scenario assertions through Python's standard unittest runner."""

from __future__ import annotations

import unittest

import test_planner


class PlannerScenarioTests(unittest.TestCase):
    pass


for _scenario_name in sorted(name for name in dir(test_planner) if name.startswith("test_")):
    _scenario = getattr(test_planner, _scenario_name)

    def _run_scenario(self: PlannerScenarioTests, scenario=_scenario) -> None:
        scenario()

    setattr(PlannerScenarioTests, _scenario_name, _run_scenario)

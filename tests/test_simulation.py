import unittest
from dataclasses import replace

from abyss_ai.simulation import SimulationRunner, build_scenario


class SimulationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = SimulationRunner()

    def approved_report(self, name: str):
        scenario = build_scenario(name)
        prepared = self.runner.prepare(scenario)
        approval = self.runner.issue_simulation_approval(prepared)
        return self.runner.run(scenario, approval)

    def test_ready_without_approval_stops_at_review_gate(self) -> None:
        report = self.runner.run(build_scenario("ready"))
        self.assertEqual(report.final_status, "review_required")
        self.assertEqual(report.recorded_actions, ())
        self.assertFalse(report.real_input_backend)

    def test_ready_with_approval_completes_recording_only(self) -> None:
        report = self.approved_report("ready")
        self.assertEqual(report.final_status, "completed")
        self.assertEqual(report.recorded_actions, ("skill", "basic_attack"))
        self.assertFalse(report.real_input_backend)

    def test_not_ready_returns_cultivation_and_no_actions(self) -> None:
        report = self.runner.run(build_scenario("not-ready"))
        self.assertEqual(report.final_status, "cultivation_required")
        self.assertGreater(report.cultivation_steps, 0)
        self.assertEqual(report.recorded_actions, ())

    def test_low_confidence_requires_review(self) -> None:
        report = self.runner.run(build_scenario("low-confidence"))
        self.assertEqual(report.final_status, "scan_review_required")
        self.assertEqual(report.recorded_actions, ())

    def test_ocr_conflict_requires_review(self) -> None:
        report = self.runner.run(build_scenario("ocr-conflict"))
        self.assertEqual(report.final_status, "scan_review_required")
        self.assertEqual(report.recorded_actions, ())

    def test_unsafe_screen_is_blocked_without_action(self) -> None:
        report = self.approved_report("unsafe-screen")
        self.assertEqual(report.final_status, "blocked")
        self.assertIn("screen_blocked", report.stop_reason or "")
        self.assertEqual(report.recorded_actions, ())

    def test_changed_plan_hash_invalidates_approval(self) -> None:
        scenario = build_scenario("ready")
        prepared = self.runner.prepare(scenario)
        approval = replace(self.runner.issue_simulation_approval(prepared), plan_hash="changed")
        report = self.runner.run(scenario, approval)
        self.assertEqual(report.final_status, "blocked")
        self.assertEqual(report.recorded_actions, ())

    def test_missing_state_transition_stops_loop(self) -> None:
        scenario = build_scenario("ready")
        repeated = replace(
            scenario,
            battle_states=(scenario.battle_states[0], scenario.battle_states[0]),
        )
        prepared = self.runner.prepare(repeated)
        approval = self.runner.issue_simulation_approval(prepared)
        report = self.runner.run(repeated, approval)
        self.assertEqual(report.stop_reason, "state_transition_missing")
        self.assertEqual(report.recorded_actions, ("skill",))


if __name__ == "__main__":
    unittest.main()

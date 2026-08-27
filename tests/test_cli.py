import io
import json
import unittest
from contextlib import redirect_stdout

from abyss_ai.cli import main


class CliTests(unittest.TestCase):
    def test_status_reports_no_real_input_backend(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["status"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["real_input_backend"])
        self.assertEqual(data["default_policy"], "deny")


if __name__ == "__main__":
    unittest.main()


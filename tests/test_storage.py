import tempfile
import unittest
from pathlib import Path

from abyss_ai.infrastructure import LocalJsonStore


class LocalJsonStoreTests(unittest.TestCase):
    def test_round_trip_local_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalJsonStore(Path(directory))
            path = store.save("account-1", {"account_id": "local", "characters": []})
            self.assertTrue(path.exists())
            self.assertEqual(store.load("account-1")["account_id"], "local")

    def test_rejects_path_traversal_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalJsonStore(Path(directory))
            with self.assertRaisesRegex(ValueError, "invalid"):
                store.save("../outside", {})

    def test_rejects_nested_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalJsonStore(Path(directory))
            with self.assertRaisesRegex(ValueError, "sensitive"):
                store.save("bad", {"session": {"access_token": "secret"}})


if __name__ == "__main__":
    unittest.main()


import unittest
from uuid import uuid4

from abyss_ai.domain import CharacterBuild, EquippedLightCone, EquippedRelic, RelicSlot, StatValue
from tests.helpers import scanned


class DomainBindingTests(unittest.TestCase):
    def test_rejects_cross_account_light_cone(self) -> None:
        account = uuid4()
        other = uuid4()
        light_cone = EquippedLightCone(other, "cone", scanned(80), scanned(1))

        with self.assertRaisesRegex(ValueError, "another account"):
            CharacterBuild(account, "hero", scanned(80), scanned(0), light_cone=light_cone)

    def test_rejects_duplicate_relic_slot(self) -> None:
        account = uuid4()

        def relic(set_id: str) -> EquippedRelic:
            return EquippedRelic(
                account,
                "hero",
                RelicSlot.HEAD,
                scanned(set_id),
                scanned(15),
                scanned(StatValue("hp", 705)),
            )

        with self.assertRaisesRegex(ValueError, "duplicate relic slot"):
            CharacterBuild(
                account,
                "hero",
                scanned(80),
                scanned(0),
                relics=(relic("set-a"), relic("set-b")),
            )

    def test_low_confidence_correction_is_visible(self) -> None:
        build = CharacterBuild(
            uuid4(),
            "hero",
            scanned(80),
            scanned(0, confidence=0.5, needs_review=True),
        )
        self.assertTrue(build.needs_review)


if __name__ == "__main__":
    unittest.main()


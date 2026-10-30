from __future__ import annotations

import unittest

from starhelp_knowledge.public_rag import chunk_identity, chunk_text, grounded_answer, tokenize


class PublicRagUnitTests(unittest.TestCase):
    def test_chunking_and_identity_are_deterministic(self) -> None:
        text = ("Synthetic public evidence sentence. " * 40).strip()
        chunks = chunk_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks, chunk_text(text))
        identity = chunk_identity(
            source_id="fixture:source", evidence_id="fixture:evidence", revision=1,
            content_hash="a" * 64, chunk_index=0,
        )
        self.assertEqual(identity, chunk_identity(
            source_id="fixture:source", evidence_id="fixture:evidence", revision=1,
            content_hash="a" * 64, chunk_index=0,
        ))
        self.assertNotEqual(identity, chunk_identity(
            source_id="fixture:source", evidence_id="fixture:evidence", revision=2,
            content_hash="a" * 64, chunk_index=0,
        ))

    def test_tokenizer_handles_chinese_and_english_terms(self) -> None:
        self.assertEqual(tokenize("星铁 public guide"), ["星铁", "public", "guide"])

    def test_conflicting_evidence_abstains_and_keeps_both_citations(self) -> None:
        def hit(evidence_id: str, relation: str) -> dict[str, object]:
            return {
                "chunk_id": evidence_id, "evidence_id": evidence_id, "revision": 1,
                "content_hash": "a" * 64, "title": evidence_id, "url": f"https://example.test/{evidence_id}",
                "locator": {}, "published_at": None, "observed_at": "2026-10-30T00:00:00Z",
                "relation": relation, "excerpt": "Synthetic conflicting evidence.", "score": 1.0,
            }

        result = grounded_answer([hit("fixture:support", "supports"), hit("fixture:refute", "refutes")])
        self.assertTrue(result["abstained"])
        self.assertEqual(result["abstention_reason"], "conflicting_evidence")
        self.assertIsNone(result["answer"])
        self.assertEqual({item["evidence_id"] for item in result["citations"]}, {"fixture:support", "fixture:refute"})


if __name__ == "__main__":
    unittest.main()

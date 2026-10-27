import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_registry as registry  # noqa: E402


class ModelRegistryTests(unittest.TestCase):
    def test_registry_matches_live_models(self):
        self.assertEqual(registry.problems(), [])

    def test_every_live_model_has_a_training_end_date(self):
        for name, entry in registry.load_registry()["models"].items():
            self.assertRegex(entry["trained_through"] or "", r"^\d{4}-\d{2}-\d{2}$", name)

    def test_promote_copies_candidate_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            live, candidates = Path(tmp), Path(tmp) / "candidates"
            candidates.mkdir()
            name = "blr_d3_direct.pkl"
            (live / name).write_bytes(pickle.dumps({"trained_through": "2026-09-08"}))
            (candidates / name).write_bytes(pickle.dumps({"trained_through": "2026-10-26"}))
            (candidates / "blr_d3_direct_metrics.json").write_text("{}", encoding="utf-8")
            with patch.multiple(registry, MODEL_DIR=live, CANDIDATE_DIR=candidates,
                                REGISTRY_PATH=live / "model_registry.json",
                                LIVE_MODELS={name: "BLR"}):
                registry.save_registry({"models": {name: {
                    "sha256": registry.sha256(live / name), "trained_through": "2026-09-08",
                    "promoted_at": "2026-09-09", "note": "old"}}, "history": []})
                registry.promote("BLR 3.1% vs 3.7%", None)
                saved = json.loads((live / "model_registry.json").read_text(encoding="utf-8"))
                self.assertEqual(registry.problems(), [])
            self.assertEqual(saved["models"][name]["trained_through"], "2026-10-26")
            self.assertEqual(saved["history"][0]["trained_through"], "2026-09-08")
            self.assertTrue((live / "blr_d3_direct_metrics.json").exists())


if __name__ == "__main__":
    unittest.main()

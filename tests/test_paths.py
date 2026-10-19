"""Behavioral coverage for bundled paths, CLI paths and historical provenance."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from benchmarks.analyze_results import verify_sources

ROOT = Path(__file__).resolve().parents[1]


class PathTests(unittest.TestCase):
    def run_module(self, module, args, cwd):
        env = os.environ | {"PYTHONPATH": str(ROOT)}
        # Redirect report artifacts to the disposable folder, preserving real I/O.
        code = ("import importlib; from pathlib import Path; "
                f"module = importlib.import_module({module!r}); "
                f"module.ROOT = Path({str(cwd)!r}); module.main()")
        return subprocess.run([sys.executable, "-c", code, *args], cwd=cwd,
                              env=env, text=True, capture_output=True, timeout=30)

    def test_bundled_positions_load_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, "-c",
                "from benchmarks.experiments import load_positions; "
                "print(len(load_positions()))"], cwd=temp,
                env=os.environ | {"PYTHONPATH": str(ROOT)},
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "12")

    def test_explicit_fixture_and_output_paths_follow_invoking_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            fixture = b'[{"name": "custom start", "category": "opening"}]'
            (folder / "input.json").write_bytes(fixture)
            result = subprocess.run([sys.executable, "-m", "benchmarks.experiments",
                "--positions", "input.json", "--out", "measured", "--mode", "games",
                "--budgets", "0.01", "--game-starts", "1", "--max-plies", "1"],
                cwd=temp, env=os.environ | {"PYTHONPATH": str(ROOT)},
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads((folder / "measured/metadata.json").read_text())
            self.assertEqual(metadata["fixture_sha256"], hashlib.sha256(fixture).hexdigest())
            self.assertTrue(metadata["completed_utc"])
            self.assertEqual(metadata["command"]["positions"], "input.json")
            self.assertEqual(metadata["command"]["out"], "measured")
            self.assertTrue((folder / "measured/games.csv").is_file())
            verify_sources(folder / "measured", metadata["source_sha256"])
            altered = metadata["source_sha256"] | {"chess_duel/engine.py": "0" * 64}
            with self.assertRaises(ValueError):
                verify_sources(folder / "measured", altered)

    def test_archived_ablation_sources_and_mismatch_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            study = root / "study"
            shutil.copytree(ROOT / "results/followup/ablation", study / "ablation")
            shutil.copytree(ROOT / "results/followup/source", study / "source")
            args = ["--analyze-only", "--out", str(study / "ablation")]
            result = self.run_module("benchmarks.followup_experiments", args, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((study / "ablation/analysis.json").read_text())
            self.assertEqual(summary["searches"], 912)
            (study / "source/engine.py").write_bytes(b"changed archived engine")
            result = self.run_module("benchmarks.followup_experiments", args, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source changed", result.stderr.lower())

    def test_archived_game_sources_and_mismatch_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            study = root / "study"
            shutil.copytree(ROOT / "results/followup/games-matched", study / "games-matched")
            shutil.copytree(ROOT / "results/followup/source", study / "source")
            args = ["--followup-games", str(study / "games-matched")]
            result = self.run_module("benchmarks.analyze_results", args, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((study / "games-matched/analysis.json").read_text())
            self.assertEqual([g["completed_score"] for g in summary], [.8125, .875])
            (study / "source/experiments.py").write_bytes(b"changed archived runner")
            result = self.run_module("benchmarks.analyze_results", args, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source changed", result.stderr.lower())

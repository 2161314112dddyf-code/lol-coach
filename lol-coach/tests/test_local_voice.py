"""Offline wrapper checks only; no model inference or voice-quality assertions."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_local_voice.py"
SPEC = importlib.util.spec_from_file_location("run_local_voice", SCRIPT)
voice = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice)


class LocalVoiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="lol-local-voice-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.model = self.root / "model"
        for relative in voice.REQUIRED_ASSETS:
            target = self.model / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic-test-asset")
        (self.model / "config.yaml").write_text("version: 2.5\n", encoding="utf-8")
        self.engine = self.root / "engine"
        (self.engine / "indextts").mkdir(parents=True)
        (self.engine / "indextts/infer_v2_5.py").write_text("raise AssertionError('Do not import during file checks')\n")
        self.text = self.root / "text.txt"
        self.text.write_text("潘森这里不能交 W。", encoding="utf-8")
        self.reference = self.root / "reference.wav"
        self.reference.write_bytes(b"synthetic-reference")
        self.output = self.root / "output.wav"
        self.arguments = [
            "--text-file", str(self.text), "--reference-audio", str(self.reference),
            "--output", str(self.output), "--model-dir", str(self.model),
            "--engine-dir", str(self.engine),
            "--source-provenance", str(self.root / "absent-source.json"),
            "--asset-manifest", str(self.root / "absent-main.json"),
            "--auxiliary-manifest", str(self.root / "absent-auxiliary.json"),
        ]

    def run_cli(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = voice.main(self.arguments + list(extra))
        return result, stdout.getvalue(), stderr.getvalue()

    def test_check_only_does_not_import_model_or_create_audio(self):
        with patch.object(voice.importlib, "import_module", side_effect=AssertionError("No runtime imports")):
            code, output, _ = self.run_cli("--check-only")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "files_ready")
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".manifest.json").exists())

    def test_partial_download_does_not_count_as_weight(self):
        target = self.model / "gpt.pth"
        target.rename(target.with_suffix(".pth.part"))
        code, output, _ = self.run_cli("--check-only")
        self.assertEqual(code, 2)
        report = json.loads(output)
        item = next(item for item in report["assets"] if item["path"] == "gpt.pth")
        self.assertEqual(item["status"], "missing")
        self.assertTrue(item["partial_download_present"])

    def test_hash_mismatch_is_reported_with_actual_digest(self):
        checks, errors = voice.check_assets(self.model, {"gpt.pth": {"expected_sha256": "0" * 64}}, True)
        item = next(item for item in checks if item["path"] == "gpt.pth")
        self.assertEqual(item["status"], "hash_mismatch")
        self.assertNotEqual(item["actual_sha256"], item["expected_sha256"])
        self.assertTrue(errors)

    def test_truncated_weight_is_rejected_before_hashing(self):
        checks, errors = voice.check_assets(self.model, {"gpt.pth": {"expected_bytes": 1024}}, False)
        self.assertEqual(next(item for item in checks if item["path"] == "gpt.pth")["status"], "size_mismatch")
        self.assertTrue(errors)

    def test_network_connections_are_blocked_and_guard_is_restored(self):
        original = socket.socket.connect
        with voice.block_network() as attempts:
            with socket.socket() as connection:
                with self.assertRaisesRegex(RuntimeError, "Network is disabled"):
                    connection.connect(("127.0.0.1", 9))
            with self.assertRaises(RuntimeError):
                socket.create_connection(("127.0.0.1", 9))
        self.assertEqual(len(attempts), 2)
        self.assertIs(socket.socket.connect, original)

    def test_runtime_failure_is_persisted_without_fake_audio_or_metrics(self):
        previous_cwd = Path.cwd()
        with patch.object(voice.importlib, "import_module", side_effect=ImportError("synthetic missing torch")):
            code, _, _ = self.run_cli()
        self.assertEqual(code, 1)
        manifest = json.loads(self.output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["error"]["type"], "ImportError")
        self.assertIsNone(manifest["audio"])
        self.assertIsNone(manifest["generation_seconds"])
        self.assertIsNone(manifest["peak_torch_cuda_allocated_bytes"])
        self.assertEqual(manifest["listening_review"], "not_performed")
        self.assertEqual(Path.cwd(), previous_cwd)

    def test_existing_output_is_not_overwritten(self):
        self.output.write_bytes(b"keep-user-audio")
        code, _, errors = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("Refusing to overwrite", errors)
        self.assertEqual(self.output.read_bytes(), b"keep-user-audio")

    def test_empty_narration_is_rejected(self):
        self.text.write_text(" \n", encoding="utf-8")
        code, output, _ = self.run_cli("--check-only")
        self.assertEqual(code, 2)
        self.assertIn("Narration text must not be empty", json.loads(output)["errors"])


if __name__ == "__main__":
    unittest.main()

"""Generate a WAV with a separately installed local IndexTTS-2.5 environment.

Run this script with that environment's Python. --check-only uses only the
standard library and does not load models or claim that inference works.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import re
import socket
import sys
import time
import traceback
import wave


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "data/private/local_voice"
REQUIRED_ASSETS = (
    "config.yaml", "gpt.pth", "s2mel.pth", "codec.pth",
    "wav2vec2bert_stats.pt", "feat1.pt", "feat2.pt",
    "multilingual_zh_ja_yue_char_del.tiktoken",
    "hf_cache/w2v-bert-2.0/config.json",
    "hf_cache/w2v-bert-2.0/preprocessor_config.json",
    "hf_cache/w2v-bert-2.0/model.safetensors",
    "hf_cache/campplus_cn_common.bin",
    "hf_cache/bigvgan/config.json", "hf_cache/bigvgan/bigvgan_generator.pt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expected_assets(main_manifest: Path, auxiliary_manifest: Path) -> dict:
    """Read download evidence, without mistaking expected hashes for observed ones."""
    expected = {}
    if main_manifest.is_file():
        for item in read_json(main_manifest).get("Data", {}).get("Files", []):
            if item.get("Type") == "blob":
                expected[item["Path"]] = {
                    "expected_bytes": item.get("Size"),
                    "expected_sha256": item.get("Sha256") or None,
                    "revision": item.get("Revision"),
                }
    if auxiliary_manifest.is_file():
        for repo, revision, filename, folder, digest in read_json(auxiliary_manifest).get("jobs", []):
            name = (Path("hf_cache") / folder / filename).as_posix()
            expected[name] = {
                "expected_bytes": None, "expected_sha256": digest,
                "revision": revision, "repository": repo,
            }
    return expected


def check_assets(model_dir: Path, expected: dict, verify_hashes: bool) -> tuple[list, list]:
    checks, errors = [], []
    for name in REQUIRED_ASSETS:
        path = model_dir / name
        spec = expected.get(name, {})
        item = {"path": name, **spec, "actual_bytes": None,
                "actual_sha256": None, "status": "missing"}
        if not path.is_file():
            item["partial_download_present"] = any(path.parent.glob(path.name + ".part*"))
            errors.append(f"Missing complete asset: {path}")
        else:
            item["actual_bytes"] = path.stat().st_size
            if item["actual_bytes"] == 0:
                item["status"] = "empty"
            elif spec.get("expected_bytes") is not None and item["actual_bytes"] != spec["expected_bytes"]:
                item["status"] = "size_mismatch"
            elif verify_hashes:
                item["actual_sha256"] = sha256(path)
                if spec.get("expected_sha256"):
                    item["status"] = ("hash_verified" if item["actual_sha256"] == spec["expected_sha256"]
                                      else "hash_mismatch")
                else:
                    item["status"] = "hashed_without_source_digest"
            else:
                item["status"] = "present_hash_not_checked"
            if item["status"] in {"empty", "size_mismatch", "hash_mismatch"}:
                errors.append(f"Invalid asset ({item['status']}): {path}")
        checks.append(item)
    return checks, errors


@contextmanager
def block_network():
    """Block Python socket connections during model import and inference."""
    connect, connect_ex, create_connection = socket.socket.connect, socket.socket.connect_ex, socket.create_connection
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("socket_connection_blocked")
        raise RuntimeError("Network is disabled for local voice generation; pre-cache required assets.")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
        socket.create_connection = create_connection


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as audio:
        frames, rate = audio.getnframes(), audio.getframerate()
        if frames <= 0 or rate <= 0:
            raise ValueError("Generated WAV has no audio frames.")
        return {"sample_rate_hz": rate, "channels": audio.getnchannels(),
                "sample_width_bytes": audio.getsampwidth(), "frames": frames,
                "duration_seconds": frames / rate}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--text-file", type=Path, required=True)
    result.add_argument("--reference-audio", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True, help="New .wav file; existing output is never overwritten")
    result.add_argument("--engine-dir", type=Path, default=LOCAL / "vendor/index-tts")
    result.add_argument("--model-dir", type=Path, default=LOCAL / "models/index-tts-2.5")
    result.add_argument("--source-provenance", type=Path, default=LOCAL / "source-provenance.json")
    result.add_argument("--asset-manifest", type=Path, default=LOCAL / "model-files.json")
    result.add_argument("--auxiliary-manifest", type=Path, default=LOCAL / "auxiliary-manifest.json")
    result.add_argument("--device", default="cuda:0", help="CUDA device, or cpu for an explicitly slower run")
    result.add_argument("--precision", choices=("bf16", "fp32"), default="bf16")
    result.add_argument("--duration-factor", type=float, default=1.0, help="0.5–2.0; >1 slows speech")
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--check-only", action="store_true")
    result.add_argument("--verify-hashes", action="store_true", help="Read full weight files and compare available source digests")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    for name in ("text_file", "reference_audio", "output", "engine_dir", "model_dir",
                 "source_provenance", "asset_manifest", "auxiliary_manifest"):
        setattr(args, name, getattr(args, name).resolve())
    errors = []
    if not 0.5 <= args.duration_factor <= 2.0:
        errors.append("--duration-factor must be between 0.5 and 2.0")
    if args.output.suffix.lower() != ".wav":
        errors.append("--output must end with .wav")
    for path in (args.text_file, args.reference_audio, args.engine_dir / "indextts/infer_v2_5.py"):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"Missing or empty input: {path}")
    text = args.text_file.read_text(encoding="utf-8-sig") if args.text_file.is_file() else ""
    if not text.strip():
        errors.append("Narration text must not be empty")
    config = args.model_dir / "config.yaml"
    if config.is_file() and not re.search(r"(?m)^version:\s*['\"]?2\.5['\"]?\s*$", config.read_text(encoding="utf-8-sig")):
        errors.append("This entry point requires an IndexTTS-2.5 config")
    assets, asset_errors = check_assets(args.model_dir, expected_assets(args.asset_manifest, args.auxiliary_manifest), args.verify_hashes)
    errors.extend(asset_errors)
    if args.check_only:
        print(json.dumps({"status": "files_ready" if not errors else "incomplete",
                          "scope": "File checks only; dependencies, GPU, inference and listening not tested",
                          "assets": assets, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 2
    manifest_path = args.output.with_suffix(".manifest.json")
    temporary_output = args.output.with_suffix(".partial.wav")
    for path in (args.output, manifest_path, temporary_output):
        if path.exists():
            errors.append(f"Refusing to overwrite existing file: {path}")
    if errors:
        print(json.dumps({"status": "incomplete", "errors": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine_source = args.engine_dir / "indextts/infer_v2_5.py"
    manifest = {
        "schema_version": 1, "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": {"name": "IndexTTS-2.5", "directory": str(args.engine_dir),
                   "inference_source_sha256": sha256(engine_source),
                   "source_provenance": read_json(args.source_provenance) if args.source_provenance.is_file() else None},
        "model": {"directory": str(args.model_dir), "config_sha256": sha256(config), "assets": assets},
        "text": {"path": str(args.text_file), "sha256": sha256(args.text_file), "characters": len(text)},
        "reference_audio": {"path": str(args.reference_audio), "sha256": sha256(args.reference_audio)},
        "parameters": {"device": args.device, "precision": args.precision, "language": "ZH",
                       "duration_factor": args.duration_factor, "seed": args.seed,
                       "qwen_emotion": False, "cuda_kernel": False, "deepspeed": False},
        "runtime": {"python": sys.version, "python_executable": sys.executable,
                    "torch": None, "cuda_version": None, "gpu": None},
        "network_guard": "Python socket connections blocked; not an OS firewall audit",
        "blocked_connection_attempts": 0, "model_load_seconds": None, "generation_seconds": None,
        "total_seconds": None, "peak_torch_cuda_allocated_bytes": None,
        "peak_torch_cuda_reserved_bytes": None, "audio": None, "error": None,
        "listening_review": "not_performed",
    }

    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save_manifest()
    started = time.perf_counter()
    previous_cwd = Path.cwd()
    previous_path = list(sys.path)
    offline_keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "MODELSCOPE_OFFLINE")
    previous_environment = {key: os.environ.get(key) for key in offline_keys}
    torch = None
    cuda_metrics_available = False
    blocked_attempts = []
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["MODELSCOPE_OFFLINE"] = "1"
        sys.path.insert(0, str(args.engine_dir))
        os.chdir(args.engine_dir)
        with block_network() as blocked_attempts:
            torch = importlib.import_module("torch")
            manifest["runtime"].update(torch=torch.__version__, cuda_version=torch.version.cuda)
            if args.device.startswith("cuda"):
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA is unavailable in this Python environment; no CPU fallback was performed")
                torch.cuda.init()
                torch.cuda.reset_peak_memory_stats(args.device)
                cuda_metrics_available = True
                manifest["runtime"]["gpu"] = torch.cuda.get_device_name(args.device)
            random.seed(args.seed)
            torch.manual_seed(args.seed)
            engine = importlib.import_module("indextts.infer_v2_5").IndexTTS2
            tts = engine(cfg_path=str(config), model_dir=str(args.model_dir), device=args.device,
                         use_bf16=args.precision == "bf16", use_cuda_kernel=False,
                         use_deepspeed=False, use_accel=False, use_torch_compile=False, use_qwen_emo=False)
            manifest["model_load_seconds"] = time.perf_counter() - started
            save_manifest()
            inference_started = time.perf_counter()
            tts.infer(spk_audio_prompt=str(args.reference_audio), text=text,
                      output_path=str(temporary_output), lang="ZH", use_emo_text=False,
                      use_random=False, duration_factor=args.duration_factor, verbose=True)
            if args.device.startswith("cuda"):
                torch.cuda.synchronize(args.device)
            manifest["generation_seconds"] = time.perf_counter() - inference_started
            metadata = wav_info(temporary_output)
            temporary_output.rename(args.output)
            manifest["audio"] = {"path": str(args.output), "sha256": sha256(args.output), **metadata}
            manifest["status"] = "generated"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        traceback.print_exc()
        print(f"Local voice failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = previous_path
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        manifest["blocked_connection_attempts"] = len(blocked_attempts)
        manifest["total_seconds"] = time.perf_counter() - started
        if cuda_metrics_available:
            manifest["peak_torch_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated(args.device)
            manifest["peak_torch_cuda_reserved_bytes"] = torch.cuda.max_memory_reserved(args.device)
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_manifest()
    print(json.dumps({"status": manifest["status"], "manifest": str(manifest_path), "audio": manifest["audio"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "generated" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Voice cloning utility for Coqui TTS XTTS v2 with a cached, reusable model service.
- Provides a CLI for one-off synthesis
- Exposes a clone_voice() API that reuses a loaded model across calls
- Exposes warm_model() and is_model_loaded() for backend progress integration
"""

import argparse
import os
import sys
import threading
from typing import Optional

try:
    import torch
    _HAS_CUDA = torch.cuda.is_available()
except Exception:
    torch = None
    _HAS_CUDA = False

try:
    from torch.serialization import add_safe_globals
except Exception:
    add_safe_globals = None

try:
    from TTS.config.shared_configs import BaseDatasetConfig
except Exception:
    BaseDatasetConfig = None

try:
    from TTS.tts.configs.xtts_config import XttsConfig
except Exception:
    XttsConfig = None

try:
    from TTS.tts.models.xtts import XttsAudioConfig
except Exception:
    XttsAudioConfig = None

from TTS.api import TTS

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"


def _collect_safe_globals():
    safe_classes = []
    for cls in (BaseDatasetConfig, XttsConfig, XttsAudioConfig):
        if cls:
            safe_classes.append(cls)
    try:
        from TTS.tts.models.xtts import XttsArgs  # type: ignore
        safe_classes.append(XttsArgs)
    except Exception:
        pass
    return safe_classes


class ModelService:
    """Thread-safe, reusable XTTS model service."""

    def __init__(self, device: Optional[str] = None) -> None:
        self.device = device or ("cuda" if _HAS_CUDA else "cpu")
        self._tts = None
        self._load_lock = threading.Lock()

    def _register_safe_globals(self) -> None:
        if not add_safe_globals:
            return
        safe_classes = _collect_safe_globals()
        if not safe_classes:
            return
        try:
            add_safe_globals(safe_classes)
            print(f"[INFO] Registered safe globals: {[c.__name__ for c in safe_classes]}")
        except Exception as e:
            print(f"[WARN] Could not register safe globals: {e}")

    def load(self) -> None:
        if self._tts is not None:
            return
        with self._load_lock:
            if self._tts is not None:
                return
            print(f"[INFO] Loading model '{MODEL_NAME}' on device: {self.device} ...", flush=True)
            self._register_safe_globals()
            self._tts = TTS(MODEL_NAME).to(self.device)

    @property
    def tts(self):
        if self._tts is None:
            self.load()
        return self._tts

    def tts_to_file(self, *, text: str, speaker_wav: str, language: str, file_path: str) -> None:
        if not os.path.isfile(speaker_wav):
            raise FileNotFoundError(f"Reference voice file not found: {speaker_wav}")
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        print(f"[INFO] Generating audio => {file_path}", flush=True)
        self.tts.tts_to_file(
            text=text,
            speaker_wav=speaker_wav,
            language=language,
            file_path=file_path,
        )


# Global cache of services per device
_SERVICES: dict[str, ModelService] = {}
_SERVICES_LOCK = threading.Lock()


def get_service(device: Optional[str] = None) -> ModelService:
    key = (device or ("cuda" if _HAS_CUDA else "cpu")).lower()
    with _SERVICES_LOCK:
        svc = _SERVICES.get(key)
        if svc is None:
            svc = ModelService(key)
            svc.load()
            _SERVICES[key] = svc
        return svc


def is_model_loaded(device: Optional[str] = None) -> bool:
    """Return True if the model service for the given device is present and loaded."""
    key = (device or ("cuda" if _HAS_CUDA else "cpu")).lower()
    with _SERVICES_LOCK:
        svc = _SERVICES.get(key)
    return bool(svc and getattr(svc, "_tts", None) is not None)


def warm_model(device: Optional[str] = None) -> None:
    """Ensure the model for the given device is loaded into memory."""
    svc = get_service(device)
    svc.load()


def clone_voice(text: str, speaker_wav: str, language: str, output: str, device: Optional[str] = None) -> None:
    """Clone a voice using a cached XTTS v2 model and synthesize text to a WAV file.

    This function is thread-safe and reuses a single model instance per device
    across repeated calls in the same process (e.g., a Flask app).
    """
    svc = get_service(device)
    svc.tts_to_file(text=text, speaker_wav=speaker_wav, language=language, file_path=output)
    print("[SUCCESS] Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone a voice with Coqui TTS XTTS v2 and synthesize text to a WAV file.",
    )
    parser.add_argument("--text", "-t", required=True, help="Text to synthesize.")
    parser.add_argument("--speaker_wav", "-s", required=True, help="Path to the reference voice WAV file.")
    parser.add_argument("--language", "-l", default="en", help="Target language code (default: en).")
    parser.add_argument("--output", "-o", default="output.wav", help="Output WAV file path (default: output.wav).")
    parser.add_argument(
        "--device",
        "-d",
        choices=["cpu", "cuda"],
        help="Execution device. Defaults to CUDA if available, otherwise CPU.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        clone_voice(
            text=args.text,
            speaker_wav=args.speaker_wav,
            language=args.language,
            output=args.output,
            device=args.device,
        )
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

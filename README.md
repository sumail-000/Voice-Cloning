# XTTS v2 Voice Cloning Demo (Coqui TTS)

This demo clones a speaker's voice from a short reference sample and synthesizes text in multiple languages using the XTTS v2 model.

Contents:
- `clone_voice.py` — CLI script to run voice cloning

Requirements:
- Python 3.9–3.11 recommended
- Windows, macOS, or Linux

## 1) Setup (recommended: virtual environment)

Windows (PowerShell):
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

macOS/Linux (bash):
```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### CPU-only install
```
pip install TTS
```

### GPU (CUDA) install (Windows/Linux)
1) Install a CUDA-enabled PyTorch build compatible with your CUDA version. Example for CUDA 12.1:
```
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio
```
2) Then install Coqui TTS:
```
pip install TTS
```
3) Verify CUDA availability (optional):
```
python - << "PY"
import torch
print("CUDA available:", torch.cuda.is_available())
PY
```
If the above prints False but you expected True, you likely installed a CPU-only PyTorch or mismatched CUDA build.

## 2) Prepare a reference voice sample
- Short clip: 6–15 seconds is usually enough.
- Clean speech, minimal background noise, no music.
- Mono WAV (16–48 kHz recommended). Many formats work, but WAV is safest.
- Place the file in this folder, e.g., `reference_voice.wav`.

## 3) Run the demo
From this `demotask` directory:

CPU:
```
python clone_voice.py --text "Ok signore, l'ho completato e qui ci sono i file WAV di riferimento." --speaker_wav "reference1.wav" --language it --output "output_it.wav" --device cpu



On first run, the model `tts_models/multilingual/multi-dataset/xtts_v2` will be downloaded automatically. The result is saved as `output.wav`.

Common language codes: `en`, `it`, `es`, `fr`, `de`, `pt`, `pl`, `nl`, `tr`, `ru`, `zh`, `ja`, `ko`.

## 4) Troubleshooting
- CUDA not used: Ensure you installed a CUDA-enabled PyTorch (see above) and your GPU drivers/CUDA runtime are installed. Then use `--device cuda`.
- Out of memory (OOM): Try CPU mode or shorter text; ensure no other GPU-heavy apps are running.
- Reference file not found: Check the `--speaker_wav` path.
- Bad audio quality: Use a cleaner/longer reference sample, reduce background noise, and avoid clipping. Try 16 kHz or 22.05/24/44.1 kHz mono WAV.
- Slow on CPU: This is expected. GPU is recommended for speed.

## 5) Notes
- This script auto-selects CUDA if available when `--device` is not provided.
- For repeatable environments, consider pinning versions in a `requirements.txt`.
- Model: `tts_models/multilingual/multi-dataset/xtts_v2`.

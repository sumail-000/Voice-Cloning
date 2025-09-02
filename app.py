import os
import time
from flask import Flask, request, jsonify, render_template_string, send_from_directory, url_for
from werkzeug.utils import secure_filename
import threading, uuid, subprocess, shutil

# Reuse existing clone function
from clone_voice import clone_voice as do_clone, warm_model, is_model_loaded

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Limit upload size to 50MB
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {"wav", "mp3", "m4a", "flac", "ogg", "opus", "webm"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Audio conversion helpers
_CONVERT_TO_WAV_EXTS = {"webm", "mp4", "m4a"}

def _ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")

def _should_convert_to_wav(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext in _CONVERT_TO_WAV_EXTS

def _convert_to_wav(input_path: str) -> str:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg or upload WAV/OGG/OPUS/MP3/M4A.")
    output_path = input_path + ".wav"
    cmd = [ffmpeg, "-y", "-i", input_path, "-ac", "1", "-ar", "22050", "-vn", output_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").splitlines()[-10:]
        raise RuntimeError("Audio conversion failed. " + "\n".join(tail))
    return output_path


INDEX_HTML = r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>XTTS Voice Cloning Demo</title>
  <style>
    :root {
      --bg1: #0f172a;
      --bg2: #111827;
      --card-bg: rgba(255, 255, 255, 0.08);
      --card-border: rgba(255, 255, 255, 0.15);
      --text: #e5e7eb;
      --muted: #94a3b8;
      --primary: #8b5cf6;
      --primary-600: #7c3aed;
      --accent: #22d3ee;
      --success: #10b981;
      --danger: #ef4444;
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica Neue, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      color: var(--text);
      background: radial-gradient(1200px 800px at 10% 0%, #1f2937, transparent 50%),
                  radial-gradient(1000px 700px at 90% 0%, #0ea5e9, transparent 50%),
                  linear-gradient(160deg, var(--bg1), var(--bg2));
      overflow-y: auto;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    .container {
      min-height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
    }

    .card {
      width: 100%;
      max-width: 980px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      box-shadow: 0 10px 30px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08);
      overflow: hidden;
    }

    .header {
      padding: 28px 28px 0 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .title {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .badge {
      display: inline-block;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: white;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.25);
    }

    h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 700;
    }

    .body {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 24px;
      padding: 24px 28px 28px 28px;
    }

    @media (max-width: 900px) {
      .body { grid-template-columns: 1fr; }
    }

    .panel {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 16px;
      padding: 18px;
    }

    p { color: var(--muted); margin: 0 0 12px 0; line-height: 1.6; }
    ul { color: var(--muted); margin: 0 0 12px 20px; }
    li { margin: 6px 0; }

    label { display: block; margin: 12px 0 8px 0; color: #cbd5e1; font-size: 14px; }

    textarea, select, input[type="file"], input[type="text"] {
      width: 100%;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(0,0,0,0.25);
      color: var(--text);
      outline: none;
    }

    /* Improve dropdown visibility */
    select {
      background: #0b1220;
      color: #f1f5f9;
      border-color: rgba(255,255,255,0.2);
    }
    /* Ensure dropdown options are readable in dark mode (supported browsers) */
    select option {
      background-color: #0b1220;
      color: #f1f5f9;
    }

    textarea { min-height: 120px; resize: vertical; }

    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 600px) { .row { grid-template-columns: 1fr; } }

    .btn {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      border: 0;
      border-radius: 12px;
      color: white;
      font-weight: 600;
      background: linear-gradient(135deg, var(--primary), var(--primary-600));
      box-shadow: 0 8px 20px rgba(139, 92, 246, 0.35);
      cursor: pointer;
      transition: transform .06s ease, filter .2s ease, box-shadow .2s ease;
    }

    .btn:disabled { filter: grayscale(0.3) brightness(0.8); cursor: not-allowed; }
    .btn:not(:disabled):hover { transform: translateY(-1px); filter: brightness(1.05); }

    .muted { color: var(--muted); font-size: 13px; }

    .divider { height: 1px; background: rgba(255,255,255,0.1); margin: 18px 0; }

    .result {
      margin-top: 12px;
      padding: 12px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(0,0,0,0.2);
    }

    .error { color: #fecaca; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.25); padding: 10px 12px; border-radius: 10px; }

    /* Loader overlay */
    .overlay {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(2, 6, 23, 0.55);
      backdrop-filter: blur(4px);
      z-index: 50;
    }

    .overlay.active { display: flex; }

    .spinner {
      width: 64px;
      height: 64px;
      border: 6px solid rgba(255,255,255,0.15);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
      box-shadow: 0 0 0 1px rgba(255,255,255,0.08) inset;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    footer { padding: 0 28px 20px 28px; color: var(--muted); font-size: 12px; text-align: right; }
    a { color: #93c5fd; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Modals and progress styling */
    .modal-overlay {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(2, 6, 23, 0.6);
      backdrop-filter: blur(6px);
      z-index: 60;
    }
    .modal-overlay.active { display: flex; }

    .modal {
      width: min(560px, 92vw);
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06);
      overflow: hidden;
    }
    .modal-header {
      padding: 16px 18px;
      display: flex;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .modal-title { font-size: 16px; font-weight: 700; }
    .modal-body { padding: 16px 18px; color: var(--muted); }
    .modal-actions { padding: 14px 18px 18px; display: flex; gap: 10px; justify-content: flex-end; }

    .btn.secondary { background: rgba(255,255,255,0.08); box-shadow: none; }
    .btn.secondary:hover { filter: brightness(1.1); }

    .steps { display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }
    .step { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; background: rgba(255,255,255,0.03); }
    .step .dot { width: 12px; height: 12px; border-radius: 50%; background: rgba(255,255,255,0.2); box-shadow: 0 0 0 2px rgba(255,255,255,0.08) inset; }
    .step.active .dot { background: var(--accent); animation: pulse 1s ease-in-out infinite; }
    .step.done .dot { background: var(--success); box-shadow: none; }
    .step.error { border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.1); }
    .step .label { color: var(--text); font-weight: 600; }
    .step .sub { color: var(--muted); font-size: 13px; }

    @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.25); } 100% { transform: scale(1); } }

    .progress-bar { height: 6px; background: rgba(255,255,255,0.08); border-radius: 999px; overflow: hidden; margin-top: 12px; }
    .progress-bar > div { height: 100%; width: 20%; background: linear-gradient(90deg, var(--primary), var(--accent)); animation: progressAnim 1.2s linear infinite; }
    @keyframes progressAnim { from { transform: translateX(-100%);} to { transform: translateX(400%);} }

    .alert { color: #fde68a; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); padding: 10px 12px; border-radius: 10px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <div class="header">
        <div class="title">
          <span class="badge">XTTS v2</span>
          <h1>Voice Cloning Demo</h1>
        </div>
        <div>
          <a class="btn secondary" href="/record">Try your own voice</a>
        </div>
      </div>

      <div class="body">
        <section class="panel">
          <p><strong>Cross‑lingual voice cloning</strong> powered by the Coqui TTS XTTS v2 model. Provide a few seconds of a reference voice, choose a language, and synthesize any text in that cloned voice.</p>
          <div class="divider"></div>
          <ul>
            <li>Upload a short reference clip (WAV/MP3/M4A/FLAC/OGG/OPUS)</li>
            <li>Select target language</li>
            <li>Type the text you want the cloned voice to speak</li>
          </ul>
          <p class="muted">Note: First run may take longer while the model downloads and loads. A loading indicator will be shown.</p>
        </section>

        <section class="panel">
          <form id="cloneForm">
            <label for="reference">Reference audio</label>
            <input id="reference" name="reference" type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.opus,.webm" required />
            <div class="muted">Use a clean clip with minimal background noise for best results.</div>

            <label for="language">Language</label>
            <select id="language" name="language" required>
              <option value="en" selected>English (en)</option>
              <option value="it">Italian (it)</option>
              <option value="es">Spanish (es)</option>
              <option value="fr">French (fr)</option>
              <option value="de">German (de)</option>
              <option value="pt">Portuguese (pt)</option>
              <option value="hi">Hindi (hi)</option>
              <option value="ar">Arabic (ar)</option>
              <option value="zh">Chinese (zh)</option>
              <option value="ja">Japanese (ja)</option>
              <option value="ko">Korean (ko)</option>
            </select>

            <label for="text">Text to synthesize</label>
            <textarea id="text" name="text" placeholder="Type the sentence to synthesize in the cloned voice..." required>Hi! This is a web demo using XTTS v2 to clone a voice and speak this sentence.</textarea>

            <div style="margin-top:14px; display:flex; align-items:center; gap:12px;">
              <button id="submitBtn" class="btn" type="submit">Clone Voice</button>
              <span class="muted">The output will appear below.</span>
            </div>

            <div id="message" style="margin-top:12px;"></div>

            <div id="result" class="result" style="display:none;">
              <strong>Result</strong>
              <audio id="audioPlayer" style="margin-top:8px; width:100%;" controls></audio>
            </div>
          </form>
        </section>
      </div>

      <footer>
        Powered by <a href="https://github.com/coqui-ai/TTS" target="_blank" rel="noopener">Coqui TTS</a> • XTTS v2
      </footer>
    </div>
  </div>

  <div id="confirmOverlay" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title" id="confirmTitle">Before you start</div>
      </div>
      <div class="modal-body">
        <div class="alert">This demo runs the XTTS model locally. The first request may take a little longer while the model loads. Subsequent runs will be faster. Thanks for your patience.</div>
        <p style="margin-top:10px;">Your reference audio stays on this machine. The generated audio will appear when processing completes.</p>
      </div>
      <div class="modal-actions">
        <button id="confirmCancel" class="btn secondary" type="button">Cancel</button>
        <button id="confirmOk" class="btn" type="button">Proceed</button>
      </div>
    </div>
  </div>

  <div id="progressOverlay" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="progressTitle">
    <div class="modal" style="max-width:680px;">
      <div class="modal-header">
        <div class="modal-title" id="progressTitle">Cloning in progress</div>
      </div>
      <div class="modal-body">
        <div class="steps" id="steps">
          <div class="step" data-step="0"><div class="dot"></div><div><div class="label">Preparing</div><div class="sub">Validating inputs</div></div></div>
          <div class="step" data-step="1"><div class="dot"></div><div><div class="label">Uploading reference</div><div class="sub">Sending audio to server</div></div></div>
          <div class="step" data-step="2"><div class="dot"></div><div><div class="label">Waiting for server</div><div class="sub">Request queued</div></div></div>
          <div class="step" data-step="3"><div class="dot"></div><div><div class="label">Loading model</div><div class="sub">First run can be slow</div></div></div>
          <div class="step" data-step="4"><div class="dot"></div><div><div class="label">Generating audio</div><div class="sub">Synthesizing speech</div></div></div>
          <div class="step" data-step="5"><div class="dot"></div><div><div class="label">Finalizing</div><div class="sub">Preparing playback</div></div></div>
        </div>
        <div class="progress-bar"><div></div></div>
        <div id="progressError" class="error" style="display:none; margin-top:12px;"></div>
      </div>
      <div class="modal-actions">
        <button id="progressClose" class="btn secondary" type="button" style="display:none;">Close</button>
      </div>
    </div>
  </div>

  <script>
    const form = document.getElementById('cloneForm');
    const submitBtn = document.getElementById('submitBtn');
    const message = document.getElementById('message');
    const resultBox = document.getElementById('result');
    const audioPlayer = document.getElementById('audioPlayer');

    const confirmOverlay = document.getElementById('confirmOverlay');
    const confirmOk = document.getElementById('confirmOk');
    const confirmCancel = document.getElementById('confirmCancel');

    const progressOverlay = document.getElementById('progressOverlay');
    const progressClose = document.getElementById('progressClose');
    const stepsRoot = document.getElementById('steps');
    const progressError = document.getElementById('progressError');

    // Single polling loop guards
    let pollHandle = null;
    let pollJobId = null;
    let pollController = null;

    function stopPolling() {
      if (pollHandle) { clearTimeout(pollHandle); pollHandle = null; }
      if (pollController) { try { pollController.abort(); } catch (_) {} pollController = null; }
      pollJobId = null;
    }

    function openConfirm(onProceed) {
      confirmOverlay.classList.add('active');
      const cleanup = () => {
        confirmOverlay.classList.remove('active');
        confirmOk.onclick = null;
        confirmCancel.onclick = null;
      };
      confirmOk.onclick = () => { cleanup(); onProceed(); };
      confirmCancel.onclick = cleanup;
    }

    function setStepState(index, state) { // state: pending|active|done|error
      const el = stepsRoot.querySelector(`.step[data-step="${index}"]`);
      if (!el) return;
      el.classList.remove('active','done','error');
      if (state === 'active') el.classList.add('active');
      if (state === 'done') el.classList.add('done');
      if (state === 'error') el.classList.add('error');
    }

    function setStepSub(index, text) {
      const el = stepsRoot.querySelector(`.step[data-step="${index}"] .sub`);
      if (el && text) el.textContent = text;
    }

    function resetSteps() {
      stepsRoot.querySelectorAll('.step').forEach(s => {
        s.classList.remove('active','done','error');
      });
      progressError.style.display = 'none';
      progressClose.style.display = 'none';
    }

    function openProgress() {
      resetSteps();
      progressOverlay.classList.add('active');
      submitBtn.disabled = true;
    }

    function closeProgress() {
      progressOverlay.classList.remove('active');
      submitBtn.disabled = false;
      stopPolling();
    }

    function showError(msg) {
      message.innerHTML = `<div class="error">${msg}</div>`;
    }

    function schedulePoll(jobId) {
      // Ensure only one polling loop per job
      if (pollJobId !== jobId) return;
      pollController = new AbortController();
      fetch(`/api/clone_status/${jobId}`, { signal: pollController.signal })
        .then(res => res.json().then(json => ({ ok: res.ok, json })))
        .then(({ ok, json }) => {
          if (!ok || !json.success) throw new Error(json.error || 'Failed to get status');
          const steps = json.steps || [];
          steps.forEach((st, i) => { setStepState(i, st.status); setStepSub(i, st.sub); });

          if (json.status === 'done') {
            if (json.audio_url) { audioPlayer.src = json.audio_url; audioPlayer.load(); }
            progressClose.style.display = 'inline-flex';
            setTimeout(() => {
              closeProgress();
              resultBox.style.display = 'block';
              audioPlayer.play().catch(()=>{});
            }, 350);
            stopPolling();
          } else if (json.status === 'error') {
            progressError.style.display = 'block';
            progressError.textContent = json.error || 'Unexpected error';
            progressClose.style.display = 'inline-flex';
            progressClose.onclick = closeProgress;
            showError(progressError.textContent);
            stopPolling();
          } else {
            // Schedule next poll after current completes
            pollHandle = setTimeout(() => schedulePoll(jobId), 1200);
          }
        })
        .catch(e => {
          progressError.style.display = 'block';
          progressError.textContent = (e && e.message) ? e.message : 'Unexpected error';
          progressClose.style.display = 'inline-flex';
          progressClose.onclick = closeProgress;
          showError(progressError.textContent);
          stopPolling();
        });
    }

    async function runClone(data) {
      resultBox.style.display = 'none';
      openProgress();
      stopPolling(); // cancel any previous

      try {
        // Kick off job
        const startRes = await fetch('/api/clone_start', { method: 'POST', body: data });
        const startJson = await startRes.json();
        if (!startRes.ok || !startJson.success) {
          throw new Error(startJson.error || 'Failed to start job');
        }
        const jobId = startJson.job_id;
        pollJobId = jobId;
        schedulePoll(jobId); // start immediate poll cycle
      } catch (err) {
        progressError.style.display = 'block';
        progressError.textContent = (err && err.message) ? err.message : 'Unexpected error';
        progressClose.style.display = 'inline-flex';
        progressClose.onclick = closeProgress;
        showError(progressError.textContent);
        stopPolling();
      }
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      message.textContent = '';
      const data = new FormData(form);
      if (!data.get('text') || !data.get('reference')) {
        showError('Please provide both text and a reference audio file.');
        return;
      }
      openConfirm(() => runClone(data));
    });
  </script>
</body>
</html>
'''


RECORD_HTML = r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Record Your Voice • XTTS Demo</title>
  <style>
    :root {
      --bg1: #0f172a;
      --bg2: #111827;
      --card-bg: rgba(255, 255, 255, 0.08);
      --card-border: rgba(255, 255, 255, 0.15);
      --text: #e5e7eb;
      --muted: #94a3b8;
      --primary: #8b5cf6;
      --primary-600: #7c3aed;
      --accent: #22d3ee;
      --success: #10b981;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica Neue, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      color: var(--text);
      background: radial-gradient(1200px 800px at 10% 0%, #1f2937, transparent 50%),
                  radial-gradient(1000px 700px at 90% 0%, #0ea5e9, transparent 50%),
                  linear-gradient(160deg, var(--bg1), var(--bg2));
      overflow-y: auto;
    }
    .container { min-height: 100%; display: flex; align-items: center; justify-content: center; padding: 40px 20px; }
    .card { width: 100%; max-width: 980px; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 20px; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: 0 10px 30px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08); overflow: hidden; }
    .header { padding: 28px 28px 0 28px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .title { display: flex; align-items: center; gap: 12px; }
    .badge { display: inline-block; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: white; background: linear-gradient(135deg, var(--primary), var(--accent)); padding: 6px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.25); }
    h1 { margin: 0; font-size: 24px; font-weight: 700; }
    .body { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 24px; padding: 24px 28px 28px 28px; }
    @media (max-width: 900px) { .body { grid-template-columns: 1fr; } }
    .panel { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 18px; }
    p { color: var(--muted); margin: 0 0 12px 0; line-height: 1.6; }
    label { display: block; margin: 12px 0 8px 0; color: #cbd5e1; font-size: 14px; }
    select, textarea, input[type="text"] { width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.12); background: rgba(0,0,0,0.25); color: var(--text); outline: none; }
    select { background: #0b1220; color: #f1f5f9; border-color: rgba(255,255,255,0.2); }
    select option { background-color: #0b1220; color: #f1f5f9; }
    textarea { min-height: 120px; resize: vertical; }
    .btn { display: inline-flex; align-items: center; gap: 10px; padding: 12px 16px; border: 0; border-radius: 12px; color: white; font-weight: 600; background: linear-gradient(135deg, var(--primary), var(--primary-600)); box-shadow: 0 8px 20px rgba(139, 92, 246, 0.35); cursor: pointer; transition: transform .06s ease, filter .2s ease, box-shadow .2s ease; }
    .btn.secondary { background: rgba(255,255,255,0.08); box-shadow: none; }
    .btn:disabled { filter: grayscale(0.3) brightness(0.8); cursor: not-allowed; }
    .muted { color: var(--muted); font-size: 13px; }
    .recorder { display:flex; align-items:center; gap:12px; padding:12px; border:1px solid rgba(255,255,255,0.12); border-radius:12px; background: rgba(0,0,0,0.25); }
    .dot { width:12px; height:12px; border-radius:50%; background: rgba(239,68,68,0.5); }
    .dot.active { background:#ef4444; animation: pulse 1s ease-in-out infinite; }
    @keyframes pulse { 0% { transform: scale(1);} 50% { transform: scale(1.25);} 100% { transform: scale(1);} }
    .controls { display:flex; gap:10px; flex-wrap:wrap; }
    .divider { height: 1px; background: rgba(255,255,255,0.1); margin: 18px 0; }
    .result { margin-top: 12px; padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.12); background: rgba(0,0,0,0.2); }
    .error { color: #fecaca; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.25); padding: 10px 12px; border-radius: 10px; }

    .modal-overlay { position: fixed; inset: 0; display: none; align-items: center; justify-content: center; background: rgba(2, 6, 23, 0.6); backdrop-filter: blur(6px); z-index: 60; }
    .modal-overlay.active { display: flex; }
    .modal { width:min(560px,92vw); background: var(--card-bg); border:1px solid var(--card-border); border-radius:16px; box-shadow: 0 10px 30px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06); overflow:hidden; }
    .modal-header { padding:16px 18px; display:flex; align-items:center; gap:10px; border-bottom:1px solid rgba(255,255,255,0.08); }
    .modal-title { font-size:16px; font-weight:700; }
    .modal-body { padding: 16px 18px; color: var(--muted); }
    .modal-actions { padding:14px 18px 18px; display:flex; gap:10px; justify-content:flex-end; }
    .steps { display:flex; flex-direction:column; gap:10px; margin-top:6px; }
    .step { display:flex; align-items:center; gap:12px; padding:10px 12px; border:1px solid rgba(255,255,255,0.08); border-radius:12px; background: rgba(255,255,255,0.03); }
    .step .dot { width:12px; height:12px; border-radius:50%; background: rgba(255,255,255,0.2); box-shadow: 0 0 0 2px rgba(255,255,255,0.08) inset; }
    .step.active .dot { background: var(--accent); animation: pulse 1s ease-in-out infinite; }
    .step.done .dot { background: var(--success); box-shadow:none; }
    .progress-bar { height:6px; background: rgba(255,255,255,0.08); border-radius:999px; overflow:hidden; margin-top:12px; }
    .progress-bar > div { height:100%; width:20%; background: linear-gradient(90deg, var(--primary), var(--accent)); animation: progressAnim 1.2s linear infinite; }
    @keyframes progressAnim { from { transform: translateX(-100%);} to { transform: translateX(400%);} }
    .alert { color: #fde68a; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); padding: 10px 12px; border-radius: 10px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <div class="header">
        <div class="title">
          <span class="badge">XTTS v2</span>
          <h1>Record Your Voice</h1>
        </div>
        <div>
          <a class="btn secondary" href="/">Back to Upload</a>
        </div>
      </div>

      <div class="body">
        <section class="panel">
          <p><strong>Try your own voice</strong> by recording a short, clear clip. Then choose a language and synthesize any text in your cloned voice.</p>
          <div class="divider"></div>
          <div class="recorder">
            <div id="recDot" class="dot"></div>
            <div style="flex:1;">
              <div style="display:flex; align-items:center; gap:10px;">
                <div id="recLabel" style="font-weight:600;">Idle</div>
                <div id="recTimer" class="muted">00:00</div>
              </div>
              <div class="muted" style="margin-top:6px;">Use a quiet environment and speak naturally for 5–10 seconds.</div>
            </div>
          </div>
          <div class="controls" style="margin-top:12px;">
            <button id="btnStart" class="btn" type="button">Start recording</button>
            <button id="btnStop" class="btn secondary" type="button" disabled>Stop</button>
            <button id="btnRetake" class="btn secondary" type="button" disabled>Retake</button>
          </div>
          <audio id="preview" style="margin-top:10px; width:100%; display:none;" controls></audio>
        </section>

        <section class="panel">
          <form id="recordForm">
            <label for="language">Language</label>
            <select id="language" name="language" required>
              <option value="en" selected>English (en)</option>
              <option value="it">Italian (it)</option>
              <option value="es">Spanish (es)</option>
              <option value="fr">French (fr)</option>
              <option value="de">German (de)</option>
              <option value="pt">Portuguese (pt)</option>
              <option value="hi">Hindi (hi)</option>
              <option value="ar">Arabic (ar)</option>
              <option value="zh">Chinese (zh)</option>
              <option value="ja">Japanese (ja)</option>
              <option value="ko">Korean (ko)</option>
            </select>

            <label for="text">Text to synthesize</label>
            <textarea id="text" name="text" placeholder="Type the sentence to synthesize in your cloned voice..." required>Hi! This is my own voice recorded and used to clone for this sentence.</textarea>

            <div style="margin-top:14px; display:flex; align-items:center; gap:12px;">
              <button id="submitBtn" class="btn" type="submit">Clone Voice</button>
              <span class="muted">Recording is required before cloning.</span>
            </div>

            <div id="message" style="margin-top:12px;"></div>

            <div id="result" class="result" style="display:none;">
              <strong>Result</strong>
              <audio id="audioPlayer" style="margin-top:8px; width:100%;" controls></audio>
            </div>
          </form>
        </section>
      </div>

      <footer style="padding: 0 28px 20px 28px; color: var(--muted); font-size: 12px; text-align: right;">
        Powered by <a href="https://github.com/coqui-ai/TTS" target="_blank" rel="noopener" style="color:#93c5fd;">Coqui TTS</a> • XTTS v2
      </footer>
    </div>
  </div>

  <!-- Confirm and Progress Modals -->
  <div id="confirmOverlay" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title" id="confirmTitle">Before you start</div>
      </div>
      <div class="modal-body">
        <div class="alert">This demo runs the XTTS model locally. The first request may take a little longer while the model loads. Subsequent runs will be faster. Thanks for your patience.</div>
        <p style="margin-top:10px;">Your voice recording stays on this machine. The generated audio will appear when processing completes.</p>
      </div>
      <div class="modal-actions">
        <button id="confirmCancel" class="btn secondary" type="button">Cancel</button>
        <button id="confirmOk" class="btn" type="button">Proceed</button>
      </div>
    </div>
  </div>

  <div id="progressOverlay" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="progressTitle">
    <div class="modal" style="max-width:680px;">
      <div class="modal-header">
        <div class="modal-title" id="progressTitle">Cloning in progress</div>
      </div>
      <div class="modal-body">
        <div class="steps" id="steps">
          <div class="step" data-step="0"><div class="dot"></div><div><div class="label">Preparing</div><div class="sub">Validating inputs</div></div></div>
          <div class="step" data-step="1"><div class="dot"></div><div><div class="label">Uploading reference</div><div class="sub">Sending audio to server</div></div></div>
          <div class="step" data-step="2"><div class="dot"></div><div><div class="label">Waiting for server</div><div class="sub">Request queued</div></div></div>
          <div class="step" data-step="3"><div class="dot"></div><div><div class="label">Loading model</div><div class="sub">First run can be slow</div></div></div>
          <div class="step" data-step="4"><div class="dot"></div><div><div class="label">Generating audio</div><div class="sub">Synthesizing speech</div></div></div>
          <div class="step" data-step="5"><div class="dot"></div><div><div class="label">Finalizing</div><div class="sub">Preparing playback</div></div></div>
        </div>
        <div class="progress-bar"><div></div></div>
        <div id="progressError" class="error" style="display:none; margin-top:12px;"></div>
      </div>
      <div class="modal-actions">
        <button id="progressClose" class="btn secondary" type="button" style="display:none;">Close</button>
      </div>
    </div>
  </div>

  <script>
    const recDot = document.getElementById('recDot');
    const recLabel = document.getElementById('recLabel');
    const recTimer = document.getElementById('recTimer');
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    const btnRetake = document.getElementById('btnRetake');
    const preview = document.getElementById('preview');

    let mediaStream = null;
    let mediaRecorder = null;
    let chunks = [];
    let recordedBlob = null;
    let t0 = 0; let timerHandle = null;

    function fmt(t){ const m = Math.floor(t/60).toString().padStart(2,'0'); const s = Math.floor(t%60).toString().padStart(2,'0'); return `${m}:${s}`; }
    function setTimer(on){ 
      if (on){ 
        t0 = Date.now(); 
        recTimer.textContent = '00:00'; 
        timerHandle = setInterval(()=>{ 
          const dt=(Date.now()-t0)/1000; 
          recTimer.textContent = fmt(dt); 
        }, 250);
      } else { 
        if (timerHandle){ clearInterval(timerHandle); timerHandle=null; } 
      }
    }

    async function startRecording(){
      try {
        const candidates = ['audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/mp4;codecs=mp4a.40.2','audio/ogg','audio/webm'];
        const mime = (window.MediaRecorder && typeof MediaRecorder.isTypeSupported === 'function') ? candidates.find(t => MediaRecorder.isTypeSupported(t)) : '';
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        mediaRecorder = mime ? new MediaRecorder(mediaStream, { mimeType: mime }) : new MediaRecorder(mediaStream);
        chunks = []; recordedBlob = null;
        mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
        mediaRecorder.onstop = () => {
          recordedBlob = new Blob(chunks, { type: mediaRecorder.mimeType });
          preview.src = URL.createObjectURL(recordedBlob);
          preview.style.display = 'block';
          recLabel.textContent = 'Recorded';
          recDot.classList.remove('active');
          setTimer(false);
          btnRetake.disabled = false;
        };
        mediaRecorder.start();
        recLabel.textContent = 'Recording...';
        recDot.classList.add('active');
        setTimer(true);
        btnStart.disabled = true;
        btnStop.disabled = false;
        btnRetake.disabled = true;
      } catch (e){
        alert('Microphone access is required to record. ' + (e && e.message ? e.message : ''));
      }
    }

    function stopRecording(){
      if (mediaRecorder && mediaRecorder.state === 'recording'){
        mediaRecorder.stop();
      }
      if (mediaStream){ mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
      btnStart.disabled = false; btnStop.disabled = true;
    }

    function retake(){
      recordedBlob = null; chunks = []; preview.src = ''; preview.style.display = 'none';
      recLabel.textContent = 'Idle'; recTimer.textContent = '00:00'; recDot.classList.remove('active');
      btnRetake.disabled = true;
    }

    btnStart.onclick = startRecording;
    btnStop.onclick = stopRecording;
    btnRetake.onclick = retake;

    // Confirmation and progress logic (same as upload page)
    const form = document.getElementById('recordForm');
    const submitBtn = document.getElementById('submitBtn');
    const message = document.getElementById('message');
    const resultBox = document.getElementById('result');
    const audioPlayer = document.getElementById('audioPlayer');

    const confirmOverlay = document.getElementById('confirmOverlay');
    const confirmOk = document.getElementById('confirmOk');
    const confirmCancel = document.getElementById('confirmCancel');

    const progressOverlay = document.getElementById('progressOverlay');
    const progressClose = document.getElementById('progressClose');
    const stepsRoot = document.getElementById('steps');
    const progressError = document.getElementById('progressError');

    let pollHandle = null; let pollJobId = null; let pollController = null;
    function stopPolling(){ if (pollHandle){ clearTimeout(pollHandle); pollHandle=null; } if (pollController){ try{pollController.abort();}catch(_){} pollController=null; } pollJobId=null; }

    function openConfirm(onProceed){
      confirmOverlay.classList.add('active');
      const cleanup=()=>{ confirmOverlay.classList.remove('active'); confirmOk.onclick=null; confirmCancel.onclick=null; };
      confirmOk.onclick=()=>{ cleanup(); onProceed(); };
      confirmCancel.onclick=cleanup;
    }

    function setStepState(index, state){ const el=stepsRoot.querySelector(`.step[data-step="${index}"]`); if(!el) return; el.classList.remove('active','done','error'); if(state==='active') el.classList.add('active'); if(state==='done') el.classList.add('done'); if(state==='error') el.classList.add('error'); }
    function setStepSub(index, text){ const el=stepsRoot.querySelector(`.step[data-step="${index}"] .sub`); if(el && text) el.textContent=text; }
    function resetSteps(){ stepsRoot.querySelectorAll('.step').forEach(s=>s.classList.remove('active','done','error')); progressError.style.display='none'; progressClose.style.display='none'; }
    function openProgress(){ resetSteps(); progressOverlay.classList.add('active'); submitBtn.disabled=true; }
    function closeProgress(){ progressOverlay.classList.remove('active'); submitBtn.disabled=false; stopPolling(); }
    function showError(msg){ message.innerHTML = `<div class="error">${msg}</div>`; }

    function schedulePoll(jobId){
      if (pollJobId !== jobId) return;
      pollController = new AbortController();
      fetch(`/api/clone_status/${jobId}`, { signal: pollController.signal })
      .then(res => res.json().then(json => ({ ok: res.ok, json })))
      .then(({ ok, json }) => {
        if (!ok || !json.success) throw new Error(json.error || 'Failed to get status');
        const steps = json.steps || [];
        steps.forEach((st,i)=>{ setStepState(i, st.status); setStepSub(i, st.sub); });
        if (json.status === 'done'){
          if (json.audio_url){ audioPlayer.src = json.audio_url; audioPlayer.load(); }
          progressClose.style.display = 'inline-flex';
          setTimeout(()=>{ closeProgress(); resultBox.style.display='block'; audioPlayer.play().catch(()=>{}); }, 350);
          stopPolling();
        } else if (json.status === 'error'){
          progressError.style.display='block'; progressError.textContent = json.error || 'Unexpected error'; progressClose.style.display='inline-flex'; progressClose.onclick = closeProgress; showError(progressError.textContent); stopPolling();
        } else {
          pollHandle = setTimeout(()=>schedulePoll(jobId), 1200);
        }
      })
      .catch(e=>{ progressError.style.display='block'; progressError.textContent = (e&&e.message)?e.message:'Unexpected error'; progressClose.style.display='inline-flex'; progressClose.onclick=closeProgress; showError(progressError.textContent); stopPolling(); });
    }

    async function runClone(){
      resultBox.style.display='none';
      if (!recordedBlob){ showError('Please record your voice before cloning.'); return; }
      openProgress(); stopPolling();
      try {
        const fd = new FormData();
        fd.append('language', document.getElementById('language').value);
        fd.append('text', document.getElementById('text').value);
        const type = (recordedBlob && recordedBlob.type) || '';
        const ext = type.includes('ogg') ? 'ogg' : (type.includes('webm') ? 'webm' : (type.includes('mp4') ? 'm4a' : 'webm'));
        fd.append('reference', recordedBlob, `recording.${ext}`);
        const startRes = await fetch('/api/clone_start', { method:'POST', body: fd });
        const startJson = await startRes.json();
        if (!startRes.ok || !startJson.success){ throw new Error(startJson.error || 'Failed to start job'); }
        const jobId = startJson.job_id; pollJobId = jobId; schedulePoll(jobId);
      } catch (err){ progressError.style.display='block'; progressError.textContent=(err&&err.message)?err.message:'Unexpected error'; progressClose.style.display='inline-flex'; progressClose.onclick=closeProgress; showError(progressError.textContent); stopPolling(); }
    }

    form.addEventListener('submit', (e)=>{ e.preventDefault(); message.textContent=''; openConfirm(runClone); });
  </script>
</body>
</html>
'''

@app.route("/record")
def record():
    return render_template_string(RECORD_HTML)

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/outputs/<path:filename>")
def serve_output(filename: str):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)

# ---------------- Progress tracking and async job execution ---------------- #
JOBS = {}
JOBS_LOCK = threading.Lock()

STEPS_TEMPLATE = [
    {"label": "Preparing", "sub": "Validating inputs", "status": "pending"},
    {"label": "Uploading reference", "sub": "Saving audio", "status": "pending"},
    {"label": "Waiting for server", "sub": "Queued", "status": "pending"},
    {"label": "Loading model", "sub": "First run may be slow", "status": "pending"},
    {"label": "Generating audio", "sub": "Synthesizing speech", "status": "pending"},
    {"label": "Finalizing", "sub": "Preparing playback", "status": "pending"},
]


def _new_job() -> dict:
    return {
        "status": "pending",
        "steps": [dict(label=s["label"], sub=s["sub"], status="pending") for s in STEPS_TEMPLATE],
        "error": None,
        "audio_url": None,
        "created": time.time(),
    }

# Cleanup policy for job registry
JOB_TTL_SECONDS = 3600  # 1 hour
MAX_JOBS = 500


def _cleanup_jobs() -> None:
    now = time.time()
    with JOBS_LOCK:
        # Remove jobs older than TTL
        to_delete = [jid for jid, job in JOBS.items() if now - job.get("created", now) > JOB_TTL_SECONDS]
        # If too many jobs, remove oldest finished (done/error)
        if len(JOBS) > MAX_JOBS:
            finished = [jid for jid, job in JOBS.items() if job.get("status") in ("done", "error")]
            finished.sort(key=lambda j: JOBS[j].get("created", 0))
            overflow = max(0, len(JOBS) - MAX_JOBS)
            to_delete.extend(finished[:overflow])
        for jid in set(to_delete):
            JOBS.pop(jid, None)


def _set_step(job_id: str, idx: int, status: str, sub: str | None = None) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        st = job["steps"][idx]
        st["status"] = status
        if sub is not None:
            st["sub"] = sub


def _set_job_status(job_id: str, status: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["status"] = status


def _set_job_error(job_id: str, msg: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["status"] = "error"
            job["error"] = msg


def _set_job_audio(job_id: str, audio_url: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["audio_url"] = audio_url


def _run_job(job_id: str, *, text: str, language: str, device: str | None, input_path: str, output_name: str, output_path: str) -> None:
    current_step = -1
    try:
        _set_job_status(job_id, "running")
        # Step 0: Preparing
        current_step = 0
        _set_step(job_id, 0, "active")
        _set_step(job_id, 0, "done")

        # Step 1: Uploading reference (already saved by start endpoint)
        current_step = 1
        _set_step(job_id, 1, "active")
        _set_step(job_id, 1, "done")

        # Step 2: Waiting for server (queue)
        current_step = 2
        _set_step(job_id, 2, "active")
        _set_step(job_id, 2, "done")

        # Step 3: Loading model
        current_step = 3
        if not is_model_loaded(device):
            _set_step(job_id, 3, "active")
            warm_model(device)
            _set_step(job_id, 3, "done")
        else:
            _set_step(job_id, 3, "done", sub="Model already in memory")

        # Step 4: Generating audio
        current_step = 4
        _set_step(job_id, 4, "active", sub="Synthesizing speech")
        ref_path = input_path
        if _should_convert_to_wav(input_path):
            if _ffmpeg_path():
                _set_step(job_id, 4, "active", sub="Converting reference audio")
                ref_path = _convert_to_wav(input_path)
                _set_step(job_id, 4, "active", sub="Synthesizing speech")
            else:
                raise RuntimeError("Reference format not supported by backend. Please install ffmpeg or upload WAV/OGG/OPUS/MP3/M4A.")
        do_clone(text=text, speaker_wav=ref_path, language=language, output=output_path, device=device)
        _set_step(job_id, 4, "done")

        # Step 5: Finalizing
        current_step = 5
        _set_step(job_id, 5, "active")
        # Avoid url_for in background thread (no app context). Use relative path.
        audio_url = f"/outputs/{output_name}"
        _set_job_audio(job_id, audio_url)
        _set_step(job_id, 5, "done")
        _set_job_status(job_id, "done")
    except Exception as e:
        failed_step = current_step if current_step >= 0 else 0
        _set_step(job_id, failed_step, "error")
        _set_job_error(job_id, str(e))


@app.route("/api/clone_start", methods=["POST"])
def api_clone_start():
    _cleanup_jobs()
    text = (request.form.get("text") or "").strip()
    language = (request.form.get("language") or "en").strip()
    device = (request.form.get("device") or None)

    file = request.files.get("reference")
    if not text:
        return jsonify({"success": False, "error": "Text is required."}), 400
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "Reference audio file is required."}), 400
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type. Use wav, mp3, m4a, flac, ogg, or opus."}), 400

    filename = secure_filename(file.filename)
    ts = int(time.time() * 1000)
    input_path = os.path.join(UPLOAD_DIR, f"{ts}_{filename}")
    output_name = f"clone_{ts}.wav"
    output_path = os.path.join(OUTPUT_DIR, output_name)

    # Save upload before returning job id
    file.save(input_path)

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = _new_job()

    threading.Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "text": text,
            "language": language,
            "device": device,
            "input_path": input_path,
            "output_name": output_name,
            "output_path": output_path,
        },
        daemon=True,
    ).start()

    return jsonify({"success": True, "job_id": job_id})


@app.route("/api/clone_status/<job_id>", methods=["GET"])
def api_clone_status(job_id: str):
    _cleanup_jobs()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"success": False, "error": "Invalid job id"}), 404
        return jsonify({"success": True, "status": job["status"], "steps": job["steps"], "error": job["error"], "audio_url": job["audio_url"]})


@app.route("/api/clone", methods=["POST"])
def api_clone():
    text = (request.form.get("text") or "").strip()
    language = (request.form.get("language") or "en").strip()
    device = (request.form.get("device") or None)

    file = request.files.get("reference")
    if not text:
        return jsonify({"success": False, "error": "Text is required."}), 400
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "Reference audio file is required."}), 400
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type. Use wav, mp3, m4a, flac, ogg, or opus."}), 400

    filename = secure_filename(file.filename)
    ts = int(time.time() * 1000)
    input_path = os.path.join(UPLOAD_DIR, f"{ts}_{filename}")
    output_name = f"clone_{ts}.wav"
    output_path = os.path.join(OUTPUT_DIR, output_name)

    file.save(input_path)

    # Convert to WAV if necessary (for formats like WEBM/M4A)
    ref_path = input_path
    if _should_convert_to_wav(input_path):
        if _ffmpeg_path():
            try:
                ref_path = _convert_to_wav(input_path)
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 400
        else:
            return jsonify({"success": False, "error": "Reference format not supported by backend. Install ffmpeg or upload WAV/OGG/OPUS/MP3/M4A."}), 400

    try:
        # Perform cloning
        do_clone(text=text, speaker_wav=ref_path, language=language, output=output_path, device=device)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    audio_url = url_for("serve_output", filename=output_name)
    return jsonify({"success": True, "audio_url": audio_url})


if __name__ == "__main__":
    # For local development
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
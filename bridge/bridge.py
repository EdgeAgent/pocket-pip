#!/usr/bin/env python3
"""
Pocket Pip — Bridge server.

Runs on the home machine (Kevin's EDGESERVER or his PC). The watch, the desk
face, and the simulator talk to this bridge; the bridge asks the brain and
returns a reply. The brain is pluggable:

  * If OLLAMA_URL is set (e.g. http://localhost:11434), messages go to a local
    Ollama model (OLLAMA_MODEL, default "llama3.2").
  * Otherwise a built-in demo brain answers, so the full watch -> bridge ->
    brain -> watch loop works end-to-end with zero setup.

The bridge also serves the web faces itself (display/ at /display/ and /,
preview/ at /preview/), so page and API share one origin — no CORS friction
when the desk face is opened from the bridge. API responses also carry
permissive CORS headers, so a page opened from file:// can still reach the
bridge on the same machine.

Voice channel (local-first, OpenAvatar bench pattern — ears + mouth on the
host):
  * POST /voice accepts {"text": "..."} (already-transcribed speech) or
    {"audio_base64": "...", "audio_mime": "audio/wav"} (raw audio).
    It returns the transcript, the brain's reply, and — when a speech
    synthesizer is configured — the reply as base64 WAV audio.
  * Speech tools are external commands, configured by env var (see below).
    faster-whisper is a library, so POCKETPIP_WHISPER_CMD points at whatever
    CLI wraps it (the `whisper` CLI, a small faster-whisper script, ...).
    Piper is a CLI already: it reads text on stdin and writes WAV to stdout.
  * If a needed command is NOT configured, /voice answers 503 with an honest
    "voice unavailable" error. Nothing is faked. The desk face also has a
    zero-install browser path (Web Speech API) that needs no bridge config.
  * GET /voice/status reports what is configured on the bridge.

Local-first: this server is meant to live on your LAN / tailnet only.
Auth: /chat and /voice require the shared token in the X-Pocket-Token header.

Endpoints:
  GET  /              -> the desk face (display/index.html)
  GET  /display/      -> the desk face, served by the bridge
  GET  /preview/      -> the round watch face, served by the bridge
  GET  /health        -> {"status": "ok", "brain": ..., "voice": {...}}
  GET  /voice/status  -> voice configuration on the bridge
  POST /chat          -> {"message": "..."}  =>  {"reply": "...", ...}
  POST /voice         -> {"text": "..."} or {"audio_base64": "..."}
                      =>  {"transcript": ..., "reply": ..., "audio_base64": ...}

Stdlib only. No pip installs. Python 3.10+.

Env vars:
  POCKETPIP_TOKEN     shared secret (default: "dev-token-change-me")
  POCKETPIP_PORT      listen port   (default: 8765)
  POCKETPIP_HOST      bind address  (default: 0.0.0.0)
  OLLAMA_URL          e.g. http://localhost:11434  (unset = demo brain)
  OLLAMA_MODEL        default llama3.2
  POCKETPIP_PIPER_CMD TTS command: reads reply text on stdin, writes WAV to
                      stdout. Example:
                      piper --model /path/to/voice.onnx --output_file -
  POCKETPIP_WHISPER_CMD
                      STT command: the audio file path replaces "{file}" in
                      the command (or is appended as the last argument);
                      the transcript must be printed to stdout. Example:
                      whisper {file} --model small --output_format txt
"""

import base64
import json
import mimetypes
import os
import shlex
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("POCKETPIP_TOKEN", "dev-token-change-me")
PORT = int(os.environ.get("POCKETPIP_PORT", "8765"))
HOST = os.environ.get("POCKETPIP_HOST", "0.0.0.0")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
PIPER_CMD = os.environ.get("POCKETPIP_PIPER_CMD", "").strip()
WHISPER_CMD = os.environ.get("POCKETPIP_WHISPER_CMD", "").strip()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIRS = {
    "/display": os.path.join(ROOT, "display"),
    "/preview": os.path.join(ROOT, "preview"),
}

SYSTEM_PROMPT = (
    "You are Pip, a friendly pocket AI companion who lives on a cloud. "
    "Keep replies short (1-2 sentences), warm, and plain-spoken."
)


# --------------------------------------------------------------------------
# Brains
# --------------------------------------------------------------------------

def demo_brain(message: str) -> str:
    """Built-in stand-in brain. Deterministic, cheerful, zero dependencies."""
    m = message.strip().lower()
    if not m:
        return "I'm listening — say the word."
    if any(w in m for w in ("hello", "hi", "hey")):
        return "Hey Kevin. Pip here, on the cloud, ready when you are."
    if "time" in m:
        return "It's %s here at home base." % time.strftime("%I:%M %p")
    if "weather" in m:
        return "Demo brain here — hook me to Ollama and I'll check for real. (London, ON: probably cold.)"
    if "who are you" in m or "your name" in m:
        return "I'm Pip — your pocket agent. I live on this watch and think back at the house."
    if "robot orchestra" in m:
        return "Robot Orchestra is safe on the home server. Roboto says hi."
    if "thank" in m:
        return "Anytime. That's what I'm here for."
    return "Got it: \"%s\". Demo brain received it loud and clear — wire up Ollama for real answers." % message.strip()


def ollama_brain(message: str) -> str:
    """Send the message to a local Ollama chat endpoint."""
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("message", {}).get("content") or "").strip() or "(empty reply)"


def ask_brain(message: str) -> tuple[str, str]:
    """Returns (reply, brain_used). Falls back to demo brain if Ollama fails."""
    if OLLAMA_URL:
        try:
            return ollama_brain(message), "ollama"
        except Exception as exc:  # keep the loop alive; watch shouldn't die on a model hiccup
            return "(Ollama unreachable: %s) Falling back — %s" % (exc.__class__.__name__, demo_brain(message)), "demo-fallback"
    return demo_brain(message), "demo"


# --------------------------------------------------------------------------
# Voice — ears (STT) and mouth (TTS) as external commands on the host.
# Nothing here pretends: unconfigured means unavailable, and /voice says so.
# --------------------------------------------------------------------------

def voice_status() -> dict:
    """What voice tooling is configured on this bridge host."""
    return {
        "stt_configured": bool(WHISPER_CMD),
        "tts_configured": bool(PIPER_CMD),
        "server_voice_available": bool(PIPER_CMD),
        "paths": {
            "browser": "Web Speech API in the desk face — zero install, handled client-side",
            "local": "POCKETPIP_WHISPER_CMD (ears) + POCKETPIP_PIPER_CMD (mouth) on the bridge host",
        },
        "note": "The P88 bar has no mic or speaker — voice runs through the host computer's mic and speakers.",
    }


def run_tts(text: str) -> bytes:
    """Run the configured TTS command: text on stdin, WAV bytes on stdout."""
    proc = subprocess.run(
        shlex.split(PIPER_CMD),
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError("TTS command failed (%d): %s" % (proc.returncode, proc.stderr.decode("utf-8", "replace")[:300]))
    if not proc.stdout:
        raise RuntimeError("TTS command produced no audio")
    return proc.stdout


def run_stt(audio: bytes, mime: str) -> str:
    """Write audio to a temp file and run the configured STT command."""
    suffix = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/webm": ".webm",
              "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}.get(mime, ".wav")
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="pocketpip-voice-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        if "{file}" in WHISPER_CMD:
            cmd = [part.replace("{file}", path) for part in shlex.split(WHISPER_CMD)]
        else:
            cmd = shlex.split(WHISPER_CMD) + [path]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError("STT command failed (%d): %s" % (proc.returncode, proc.stderr.decode("utf-8", "replace")[:300]))
        return proc.stdout.decode("utf-8", "replace").strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "PocketPipBridge/0.2"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pocket-Token")

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-Pocket-Token", "") == TOKEN

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _serve_static(self, prefix: str, rest: str):
        """Serve a file from display/ or preview/ — same origin as the API."""
        base = STATIC_DIRS[prefix]
        rel = rest.lstrip("/") or "index.html"
        path = os.path.normpath(os.path.join(base, rel))
        if not (path == base or path.startswith(base + os.sep)) or not os.path.isfile(path):
            self._json(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {
                "status": "ok",
                "service": "pocket-pip-bridge",
                "brain": "ollama" if OLLAMA_URL else "demo",
                "ollama_model": OLLAMA_MODEL if OLLAMA_URL else None,
                "voice": voice_status(),
                "serves": ["/display/", "/preview/"],
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
        elif path == "/voice/status":
            self._json(200, {"voice": voice_status()})
        elif path == "/" or path == "/display" or path.startswith("/display/"):
            self._serve_static("/display", path[len("/display"):])
        elif path == "/preview" or path.startswith("/preview/"):
            self._serve_static("/preview", path[len("/preview"):])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/chat":
            self._handle_chat()
        elif path == "/voice":
            self._handle_voice()
        else:
            self._json(404, {"error": "not found"})

    def _handle_chat(self):
        if not self._authorized():
            self._json(401, {"error": "bad or missing X-Pocket-Token"})
            return
        try:
            data = self._read_json()
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return
        message = str(data.get("message", "")).strip()
        if not message:
            self._json(400, {"error": "message is required"})
            return
        reply, brain = ask_brain(message)
        self._json(200, {"reply": reply, "brain": brain, "state": "talking"})

    def _handle_voice(self):
        if not self._authorized():
            self._json(401, {"error": "bad or missing X-Pocket-Token"})
            return
        try:
            data = self._read_json()
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return

        # --- ears: get a transcript, from text or from audio --------------
        transcript = str(data.get("text", "")).strip()
        if not transcript and data.get("audio_base64"):
            if not WHISPER_CMD:
                self._json(503, {
                    "error": "voice unavailable: speech-to-text is not configured on the bridge "
                             "(set POCKETPIP_WHISPER_CMD). Nothing was transcribed.",
                    "voice": voice_status(),
                })
                return
            try:
                audio = base64.b64decode(data["audio_base64"])
                transcript = run_stt(audio, str(data.get("audio_mime", "audio/wav")))
            except Exception as exc:
                self._json(502, {"error": "speech-to-text failed: %s" % exc})
                return
            if not transcript:
                self._json(422, {"error": "speech-to-text returned an empty transcript"})
                return
        if not transcript:
            self._json(400, {"error": "voice needs \"text\" or \"audio_base64\""})
            return

        # --- brain ---------------------------------------------------------
        reply, brain = ask_brain(transcript)

        # --- mouth: synthesize the reply, if a mouth is configured ---------
        if not PIPER_CMD:
            self._json(503, {
                "error": "voice unavailable: speech synthesis is not configured on the bridge "
                         "(set POCKETPIP_PIPER_CMD). The reply text is included; no audio was made.",
                "transcript": transcript,
                "reply": reply,
                "brain": brain,
                "voice": voice_status(),
            })
            return
        try:
            wav = run_tts(reply)
        except Exception as exc:
            self._json(502, {"error": "speech synthesis failed: %s" % exc,
                             "transcript": transcript, "reply": reply, "brain": brain})
            return
        self._json(200, {
            "transcript": transcript,
            "reply": reply,
            "brain": brain,
            "state": "talking",
            "audio_base64": base64.b64encode(wav).decode("ascii"),
            "audio_mime": "audio/wav",
        })

    def log_message(self, fmt, *args):  # concise log with timestamps
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args), flush=True)


def main():
    if TOKEN == "dev-token-change-me":
        print("WARNING: using the default dev token. Set POCKETPIP_TOKEN before real use.")
    print("Pocket Pip bridge on http://%s:%d  (brain: %s)" % (HOST, PORT, "ollama:" + OLLAMA_MODEL if OLLAMA_URL else "demo"))
    print("  desk face:  http://localhost:%d/display/   watch face: http://localhost:%d/preview/" % (PORT, PORT))
    vs = voice_status()
    print("  voice:      stt=%s tts=%s (browser Web Speech path needs no bridge config)"
          % ("configured" if vs["stt_configured"] else "not configured",
             "configured" if vs["tts_configured"] else "not configured"))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

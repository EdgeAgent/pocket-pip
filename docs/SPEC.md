# Pocket Pip — Specification

**Pocket Pip** is a small, local-first AI companion: a pet Pip who lives on a
cloud, listens, thinks on a brain running **in your house**, and answers.
No cloud account, no subscription, no data leaving the LAN unless you wire
it that way.

It exists in **two bodies** that share one brain (the bridge):

| Body | Hardware | State |
|---|---|---|
| **Desk face** | LESOWN P88 bar LCD on any computer | Works today |
| **Portable** | M5Stack StopWatch (ESP32-S3) | Firmware ready, hardware to buy |

---

## 1. The two bodies

### 1a. Desk face — LESOWN P88 (in Kevin's hands now)

A dumb HDMI monitor — no computer inside — which makes it a perfect face:
plug it into a laptop or the EDGESERVER and the host does all the thinking.

- **Panel:** 8.8″ ultra-wide bar LCD, **1920 × 480** IPS
- **Inputs:** mini-HDMI (video) + USB (5 V power)
- **Brand / maker:** LESOWN — Hengrui (Shenzhen) Technology Co., Ltd.
- **Software:** `display/index.html`, a kiosk page built at exactly
  1920 × 480. Pip sits on his cloud at the left; the wide strip carries the
  chat exchange, the agent state (idle / listening / thinking / talking,
  fully animated — it's a real LCD), a clock, and the connection status.
- **Brain link:** the page probes the bridge (`GET /health`) and chats via
  `POST /chat`. If the bridge isn't reachable — e.g. you opened the file
  directly — a built-in demo brain (the bridge's own demo replies, mirrored
  in JS) keeps the face alive and runs a periodic sample exchange on its own.
- **Light it up:** plug the P88 into the laptop/EDGESERVER (mini-HDMI +
  USB power), start the bridge, open **`http://localhost:8765/display/`**,
  press **F11** for fullscreen. On the P88 the page renders at scale
  exactly 1 — no stretching.
- **Voice:** the desk face has push-to-talk (the mic button) — see §2.
  The P88 itself has **no microphone and no speaker**: voice runs through
  the host computer's mic and speakers.

> **CORS note (fixed):** the bridge serves `display/` (and `preview/`)
> itself, so opened from the bridge the page and the API share an origin
> and there is no CORS friction at all. API responses also carry
> permissive CORS headers, so even a `file://` open can reach the bridge
> on the same machine; if the bridge is down entirely, the face drops to
> demo mode — by design.

### 1b. Portable — M5Stack StopWatch (the wrist version)

- **Part:** M5Stack StopWatch Dev Kit, manufacturer part **C152**
- **Chip:** ESP32-S3R8 — dual-core 240 MHz, 16 MB flash, 8 MB PSRAM
- **Screen:** 1.75″ round AMOLED touch, 466 × 466 (CO5300 driver, CST820 touch)
- **Audio:** MEMS microphone + 1 W speaker (ES8311 codec) — voice is the roadmap
- **Also on board:** BMI270 IMU, RTC, vibration motor, 450 mAh battery,
  USB-C, two programmable buttons, 52 mm / 39 g
- **Price/stock (checked 2026-11-16):** M5Stack's own store lists it at
  **US $45**. Spencer Ryan (whose reel inspired this) bought his at DigiKey;
  DigiKey carries M5Stack, but the C152's DigiKey price/stock **could not be
  verified** from search results on 2026-11-16 — check the listing before
  ordering. The Pi Hut (UK) listed it at £40.30 incl. VAT the same day.
- **Firmware:** `firmware/` (PlatformIO, M5Unified/M5GFX). Same Pip, same
  four states, drawn natively on the round AMOLED. `preview/index.html`
  mirrors that face in the browser so you can see it before the hardware lands.

---

## 2. Architecture

```
  ┌─────────────────┐   HDMI    ┌──────────────────────────────┐
  │  LESOWN P88     │◄──────────│  Host computer               │
  │  desk face      │           │  (laptop / EDGESERVER)       │
  └─────────────────┘           │   display served by bridge   │
                                │   bridge/bridge.py  :8765    │
  ┌─────────────────┐   Wi-Fi   │     ├─ GET  /health          │
  │  M5Stack        │──HTTP────►│     ├─ POST /chat            │
  │  StopWatch      │◄──JSON────│     └─ POST /voice           │
  │  (portable)     │           │        brain: Ollama (local) │
  └─────────────────┘           │        or built-in demo      │
        ▲ BLE (planned, off)    │        ears/mouth: whisper + │
        └─ relay via phone/host │        piper commands (host) │
                                └──────────────────────────────┘
```

One bridge, one brain, every body is a thin client:

- **Bridge** (`bridge/bridge.py`) — stdlib-only Python, no pip installs.
  `POST /chat {"message": "..."}` → `{"reply": "...", "brain": "...", "state": "talking"}`.
  `GET /health` reports status, which brain is active, the voice
  configuration, and what it serves. The bridge also serves the web faces
  itself — `display/` at `/display/` and `/`, `preview/` at `/preview/` —
  so page and API share an origin.
- **Brain (pluggable):** set `OLLAMA_URL` (e.g. `http://localhost:11434`)
  and the bridge forwards to a local Ollama model (`OLLAMA_MODEL`, default
  `llama3.2`). Unset — or if Ollama hiccups — a built-in demo brain answers,
  so the loop always works end-to-end with zero setup.
- **Voice (pluggable, local-first — the OpenAvatar bench pattern):**
  `POST /voice` takes `{"text": "..."}` (speech already transcribed) or
  `{"audio_base64": "...", "audio_mime": "..."}` (raw audio), and returns
  the transcript, the reply, and the reply as base64 WAV when a mouth is
  configured. Ears and mouth are **external commands on the host**:
  - `POCKETPIP_WHISPER_CMD` — speech-to-text. The audio file path replaces
    `{file}` in the command (or is appended); the transcript must print
    to stdout. faster-whisper is a library, so point this at a CLI that
    wraps it (a small faster-whisper script, the `whisper` CLI, ...).
  - `POCKETPIP_PIPER_CMD` — text-to-speech. Reads the reply text on
    stdin, writes WAV to stdout, e.g.
    `piper --model /path/to/voice.onnx --output_file -`.
  - **Honest unavailability:** if a needed command isn't set, `/voice`
    answers **503** and says exactly what is missing (the reply text is
    included on the TTS-missing path; no audio is ever faked).
    `GET /voice/status` reports the configuration.
  - **Zero-install path:** the desk face can also use the browser's Web
    Speech API (Chrome/Edge) for both ears and mouth — no bridge config
    at all. The page picks: browser speech recognition if present, else
    it records audio and posts it to `/voice`; bridge piper audio if
    returned, else browser speech synthesis. Pip's pose follows the turn:
    **listening** while recording, **talking** while the reply plays.
  - The desk face's mic and speakers are the **host computer's** — the
    P88 bar has neither.
- **Simulator** (`simulator/simulator.py`) — a CLI that pretends to be the
  watch: sends messages, prints replies and the state transitions. This is
  how the loop is tested without hardware.

---

## 3. Watch transports (three, in order)

1. **Wi-Fi HTTP (implemented).** The watch joins the home Wi-Fi and POSTs to
   the bridge on the LAN. This is the primary path and the one the firmware
   ships with.
2. **BLE fallback (planned, feature-flagged OFF).** If Wi-Fi is down, the
   watch advertises a "PocketPip" GATT service and a relay (phone or host)
   carries the message. The firmware keeps this behind
   `POCKETPIP_ENABLE_BLE=0` with a separate `pocket-pip-ble` PlatformIO env
   (NimBLE) — deliberately **not** enabled: untested radio code that
   pretends to work is worse than an honest TODO.
3. **Away from home — the honest version.** There is **no Tailscale client
   for ESP32/ESP32-S3**, and this spec will not pretend otherwise. The real
   route: the watch joins whatever Wi-Fi it's on and calls the bridge at
   the bridge host's **Tailscale Serve** (tailnet-only) or **Funnel**
   (public) HTTPS URL — the tailnet hop lives on the bridge host, not the
   chip. Set that URL as `PP_BRIDGE_URL` in `firmware/src/config.h`.
   (Spencer's reel described a Tailscale toggle on the watch itself; under
   the hood that class of setup always terminates the tunnel on a bigger
   device. Ours says so.)

---

## 4. Security model

- **Shared token:** every `/chat` and `/voice` call must carry
  `X-Pocket-Token` matching the bridge's `POCKETPIP_TOKEN`. Default is a
  placeholder dev token — the bridge prints a warning until you set a
  real one. (`/health` and `/voice/status` are unauthenticated status
  reads; they expose configuration, never credentials.)
- **Voice data:** recorded audio goes only to the STT command you
  configured on your own host, and reply text only to your TTS command.
  With local tools, audio never leaves the house — but know that the
  browser speech path (Web Speech API) is the browser vendor's service,
  not a local model; use the bridge-local path if that matters to you.
- **Exposure:** the bridge is meant to bind to LAN/tailnet only. If you use
  Tailscale **Funnel** (public internet), the token is the only lock on the
  door — use a long random one, and know that anyone with the URL + token
  can talk to your home brain.
- **Credentials in firmware:** `config.h` ships with **placeholders only**.
  Real Wi-Fi passwords/tokens go in your local copy, never in git
  (`.gitignore` covers `config.local.h`; keep filled values out of commits).
- **Local-first:** with Ollama as the brain, prompts and replies never
  leave the house.

---

## 5. Flashing the watch firmware

```bash
cd firmware
pio run -e pocket-pip -t upload     # with the StopWatch on USB-C
pio device monitor                  # 115200 baud
```

Board note: PlatformIO has no official StopWatch board definition yet, so
the env targets a generic ESP32-S3 dev board with flash (16 MB) and PSRAM
overridden to match the C152; M5Unified/M5GFX drives the actual StopWatch
hardware at runtime. Arduino IDE equivalent: M5Stack core ≥ 3.3.7, board
**M5StopWatch**, M5Unified ≥ 0.2.15 / M5GFX ≥ 0.2.21.
Before flashing, edit `firmware/src/config.h`: Wi-Fi SSID/password, bridge
URL, shared token.

---

## 6. Roadmap

**Done since the first spec:** the voice channel on the desk face
(push-to-talk → `/voice` → spoken reply, §2) and the bridge serving
`display/` + `preview/` itself (same origin, no CORS friction).

1. **Voice on the watch** — the C152 has a mic and speaker: push-to-talk →
   speech-to-text on the bridge → reply spoken back. (Today the watch
   cycles scripted lines so the loop is testable on day one; voice
   arrives with the hardware.)
2. **Real speech tools on the host** — install Piper + a whisper CLI on
   EDGESERVER and set the two env vars; the bridge plumbing is already
   proven with stub tools (TEST-RUN §6).
3. **BLE transport** — implement, hardware-verify, then flip the flag.
4. **Ollama on EDGESERVER** — point `OLLAMA_URL` at it and retire the demo
   brain to fallback duty.
5. **More faces** — the bridge doesn't care what renders Pip; any screen
   that can open the page or POST JSON can be a body.

---

## 7. Status

Proven vs. not-proven is tracked with receipts in
[`TEST-RUN.md`](TEST-RUN.md) — bridge + simulator loop, firmware compile,
and both web faces' standalone checks are recorded there. Nothing in this
spec is claimed working that isn't in that file.

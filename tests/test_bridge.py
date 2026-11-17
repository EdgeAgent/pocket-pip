#!/usr/bin/env python3
"""
Pocket Pip — bridge test suite (stdlib only, no pip installs).

Boots the real bridge on a scratch port with a test token and checks the
production behaviours:

  * /health reports the demo brain and mode honestly
  * /chat requires the token (401 without it)
  * /chat returns step events in the canonical order
    heard -> thinking -> working -> talking -> done, with thought lines
    and a "demo" mode label while the demo brain is answering
  * GET /events (token required) serves the same recorded exchange
  * /voice with nothing configured answers an honest 503 — reply text
    and step events included, no audio faked
  * static faces are served, and path traversal is refused (404)

Run:  python3 tests/test_bridge.py        (from the repo root)
"""

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 18799
BASE = "http://127.0.0.1:%d" % PORT
TOKEN = "test-token-for-suite"
CANONICAL_STEPS = ["heard", "thinking", "working", "talking", "done"]


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("pocketpip_bridge", os.path.join(ROOT, "bridge", "bridge.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("X-Pocket-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


class BridgeUnitTests(unittest.TestCase):
    """Pure-function checks on the bridge module itself."""

    def test_run_exchange_step_order_and_mode(self):
        mod = load_bridge_module()
        reply, brain, mode, steps = mod.run_exchange("What time is it at home base?")
        self.assertTrue(reply)
        self.assertEqual(brain, "demo")
        self.assertEqual(mode, "demo")  # no OLLAMA_URL in the test env
        self.assertEqual([s["step"] for s in steps], CANONICAL_STEPS)
        for s in steps:
            self.assertIn("label", s)
            self.assertIn("ms", s)
            self.assertGreaterEqual(s["ms"], 0)
        thoughts = [s["thought"] for s in steps if s["thought"]]
        self.assertGreaterEqual(len(thoughts), 3)
        self.assertTrue(any("clock" in t for t in thoughts))  # topic-aware

    def test_plan_thoughts_topic_aware(self):
        mod = load_bridge_module()
        self.assertTrue(any("Robot Orchestra" in t for t in mod.plan_thoughts("Check on Robot Orchestra for me.")))
        generic = mod.plan_thoughts("Tell me a story about magnets.")
        self.assertEqual(generic[0], "Reading that…")
        self.assertEqual(generic[-1], "Putting the reply together…")

    def test_agent_routing_and_identity_on_steps(self):
        mod = load_bridge_module()
        self.assertEqual(mod.route_agent("Research the best coffee in London."), "scout")
        self.assertEqual(mod.route_agent("Write me a caption for this photo."), "writer")
        self.assertEqual(mod.route_agent("Build me a little counter app."), "builder")
        self.assertEqual(mod.route_agent("Hey Pip, are you there?"), "pip")
        _, _, _, steps = mod.run_exchange("Research the best coffee in London.")
        agents = {s["step"]: s["agent"] for s in steps}
        self.assertEqual(agents["working"], "scout")   # the working step belongs to the specialist
        self.assertEqual(agents["heard"], "pip")       # Pip hears and talks
        self.assertEqual(agents["talking"], "pip")

    def test_agents_roster_shape(self):
        mod = load_bridge_module()
        state = mod.agents_state()
        self.assertEqual([a["id"] for a in state["agents"]], ["pip", "scout", "builder", "writer"])
        self.assertEqual(state["mode"], "demo")
        self.assertIn("Simulated roster", state["note"])  # honestly labelled
        pip = state["agents"][0]
        self.assertEqual(pip["status"], "online")


class BridgeHTTPTests(unittest.TestCase):
    """End-to-end checks against a live bridge subprocess."""

    proc = None

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["POCKETPIP_PORT"] = str(PORT)
        env["POCKETPIP_TOKEN"] = TOKEN
        env.pop("OLLAMA_URL", None)
        env.pop("POCKETPIP_PIPER_CMD", None)
        env.pop("POCKETPIP_WHISPER_CMD", None)
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "bridge", "bridge.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                status, _ = req("GET", "/health")
                if status == 200:
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("bridge did not come up on port %d" % PORT)

    @classmethod
    def tearDownClass(cls):
        if cls.proc:
            cls.proc.terminate()
            cls.proc.wait(timeout=10)

    def test_health_honest_demo(self):
        status, h = req("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(h["brain"], "demo")
        self.assertEqual(h["mode"], "demo")
        self.assertIn("/display/", h["serves"])

    def test_chat_requires_token(self):
        status, _ = req("POST", "/chat", {"message": "hi"})
        self.assertEqual(status, 401)

    def test_chat_returns_steps(self):
        status, data = req("POST", "/chat", {"message": "Hey Pip, are you there?"}, token=TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("Pip here", data["reply"])
        self.assertEqual(data["mode"], "demo")
        self.assertEqual([s["step"] for s in data["steps"]], CANONICAL_STEPS)
        self.assertGreaterEqual(len(data["thoughts"]), 3)

    def test_events_records_the_exchange(self):
        req("POST", "/chat", {"message": "Check on Robot Orchestra for me."}, token=TOKEN)
        status, ev = req("GET", "/events", token=TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(ev["last"]["message"], "Check on Robot Orchestra for me.")
        self.assertEqual([s["step"] for s in ev["last"]["steps"]], CANONICAL_STEPS)
        status, _ = req("GET", "/events")  # no token
        self.assertEqual(status, 401)

    def test_agents_endpoint(self):
        status, data = req("GET", "/agents")
        self.assertEqual(status, 200)
        self.assertEqual([a["name"] for a in data["agents"]], ["Pip", "Scout", "Builder", "Writer"])
        for a in data["agents"]:
            self.assertIn("status", a)
            self.assertIn("current_task", a)

    def test_voice_unconfigured_is_honest_503(self):
        status, data = req("POST", "/voice", {"text": "Hey Pip, are you there?"}, token=TOKEN)
        self.assertEqual(status, 503)
        self.assertIn("not configured", data["error"])
        self.assertIn("reply", data)          # text rides along
        self.assertNotIn("audio_base64", data)  # no audio faked
        self.assertEqual([s["step"] for s in data["steps"]], CANONICAL_STEPS)

    def test_faces_served_and_traversal_refused(self):
        with urllib.request.urlopen(BASE + "/display/", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(b"Pocket Pip", resp.read())
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        conn.request("GET", "/display/../bridge/bridge.py")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)

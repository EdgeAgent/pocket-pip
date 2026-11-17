#!/usr/bin/env python3
"""
Pocket Pip — Watch simulator.

Pretends to be the M5Stack StopWatch on your desk: sends chat messages to the
bridge, prints the replies, and walks through the same pet state transitions
the faces use (IDLE -> LISTENING -> THINKING -> WORKING -> TALKING -> IDLE).
It also prints the step events the bridge recorded for the exchange
(heard -> thinking -> working -> talking -> done, GET /events has the same
record) — the visible-work receipt.

Usage:
  python3 simulator.py                      # scripted 3-message demo conversation
  python3 simulator.py --interactive        # type your own messages (Ctrl-C to quit)
  python3 simulator.py --url http://192.168.1.50:8765 --token mysecret

Env fallbacks: POCKETPIP_URL, POCKETPIP_TOKEN.
Stdlib only.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

SCRIPT = [
    "Hey Pip, are you there?",
    "What time is it at home base?",
    "Check on Robot Orchestra for me.",
]


def set_state(state: str, note: str = ""):
    print("  [watch] state -> %-9s %s" % (state, note), flush=True)
    time.sleep(0.35)


def chat(url: str, token: str, message: str) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/chat",
        data=json.dumps({"message": message}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Pocket-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=65) as resp:
        return json.loads(resp.read().decode("utf-8"))


def health(url: str) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def one_turn(url: str, token: str, message: str):
    print("\nYOU: %s" % message)
    set_state("LISTENING", "(capturing message)")
    set_state("THINKING", "(POST /chat -> bridge)")
    try:
        result = chat(url, token, message)
    except urllib.error.HTTPError as e:
        print("  [watch] bridge error: HTTP %d" % e.code)
        set_state("IDLE", "(error)")
        return
    except Exception as e:
        print("  [watch] bridge unreachable: %s" % e)
        set_state("IDLE", "(error)")
        return
    set_state("WORKING", "(bridge is working — steps below)")
    for step in result.get("steps", []):
        line = "  [steps] ✓ %-8s %4dms" % (step.get("step", "?"), step.get("ms", 0))
        if step.get("thought"):
            line += "  — %s" % step["thought"]
        print(line, flush=True)
    set_state("TALKING", "(reply on screen)")
    print("PIP: %s" % result.get("reply", ""))
    print("  [watch] brain used: %s (mode: %s)" % (result.get("brain", "?"), result.get("mode", "?")))
    set_state("IDLE", "(back to the cloud)")


def main():
    ap = argparse.ArgumentParser(description="Pocket Pip watch simulator")
    ap.add_argument("--url", default=os.environ.get("POCKETPIP_URL", "http://localhost:8765"))
    ap.add_argument("--token", default=os.environ.get("POCKETPIP_TOKEN", "dev-token-change-me"))
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    print("Pocket Pip simulator -> %s" % args.url)
    try:
        h = health(args.url)
        print("Bridge health: %s (brain: %s)" % (h.get("status"), h.get("brain")))
    except Exception as e:
        print("Bridge not reachable at %s (%s). Start it first: python3 bridge/bridge.py" % (args.url, e))
        sys.exit(1)

    set_state("IDLE", "(Pip on his cloud)")
    if args.interactive:
        print("Type a message, Ctrl-C to quit.")
        try:
            while True:
                msg = input("\n> ").strip()
                if msg:
                    one_turn(args.url, args.token, msg)
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
    else:
        for msg in SCRIPT:
            one_turn(args.url, args.token, msg)
        print("\nScripted conversation complete.")


if __name__ == "__main__":
    main()

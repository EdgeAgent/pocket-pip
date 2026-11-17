#pragma once
// ---------------------------------------------------------------------------
// Pocket Pip — device configuration.
//
// PLACEHOLDERS ONLY. Put your real values here before flashing, and never
// commit real credentials to git (this file is in .gitignore territory the
// moment it holds secrets — keep a local copy instead).
// ---------------------------------------------------------------------------

// Your home Wi-Fi (2.4 GHz — the ESP32-S3 has no 5 GHz radio).
#define PP_WIFI_SSID        "YOUR_WIFI_SSID"
#define PP_WIFI_PASSWORD    "YOUR_WIFI_PASSWORD"

// The bridge running on your home machine (EDGESERVER / PC).
// LAN address for at-home use. For away-from-home use, point this at the
// bridge host's Tailscale Serve/Funnel HTTPS URL — see docs/SPEC.md
// ("Remote access — the honest version"). The ESP32 has NO native
// Tailscale client; the tailnet hop lives on the bridge host, not the chip.
#define PP_BRIDGE_URL       "http://192.168.1.50:8765"

// Shared secret. Must match POCKETPIP_TOKEN on the bridge.
#define PP_BRIDGE_TOKEN     "dev-token-change-me"

// BLE fallback transport. 0 = Wi-Fi only (default, verified path).
// 1 = also advertise the Pocket Pip BLE service (see main.cpp TODO).
#ifndef POCKETPIP_ENABLE_BLE
#define POCKETPIP_ENABLE_BLE 0
#endif

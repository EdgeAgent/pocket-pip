// ---------------------------------------------------------------------------
// Pocket Pip — watch firmware (M5Stack StopWatch / ESP32-S3, part C152)
//
// A little Pip lives on his cloud on the round AMOLED. Press button A (or
// tap the screen) and the watch sends the next scripted line to the Pocket
// Pip bridge on your home machine, then shows Pip's reply.
//
// Pet states: IDLE -> LISTENING -> THINKING -> TALKING -> IDLE
//   IDLE      Pip bobbing on his cloud.
//   LISTENING "Sending" beat while the message goes out.
//   THINKING  Animated dots while the bridge + brain work.
//   TALKING   Reply text on screen, Pip bouncing faster.
//
// Voice capture (mic -> speech-to-text) is on the roadmap (docs/SPEC.md);
// today the button cycles scripted lines so the whole loop is testable on
// real hardware the day the watch arrives.
//
// Transports:
//   1. Wi-Fi HTTP POST to the bridge (primary, implemented).
//   2. BLE fallback (feature-flagged OFF, skeleton + TODO below).
//   3. Away-from-home: the bridge URL can point at the bridge host's
//      Tailscale Serve/Funnel endpoint. There is NO Tailscale client for
//      ESP32 — the tailnet lives on the bridge host. See docs/SPEC.md.
// ---------------------------------------------------------------------------

#include <M5Unified.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"

#if POCKETPIP_ENABLE_BLE
#include <NimBLEDevice.h>
#endif

// Edge Agency palette (RGB565 via color565 at draw time)
static const uint8_t NAVY_R = 0x06, NAVY_G = 0x0A, NAVY_B = 0x14;   // #060A14
static const uint8_t GOLD_R = 0xE8, GOLD_G = 0xB8, GOLD_B = 0x4B;   // #E8B84B
static const uint8_t TEAL_R = 0x2D, TEAL_G = 0xD4, TEAL_B = 0xBF;   // #2DD4BF

enum PetState { IDLE, LISTENING, THINKING, TALKING, OFFLINE };
static PetState petState = IDLE;
static String lastReply = "Tap or press A to talk to Pip.";
static unsigned long stateSince = 0;
static int scriptIdx = 0;

// Scripted user lines (stand-in until mic + STT lands).
static const char* kScript[] = {
    "Hey Pip, are you there?",
    "What time is it at home base?",
    "Check on Robot Orchestra for me.",
};
static const int kScriptCount = sizeof(kScript) / sizeof(kScript[0]);

static M5Canvas canvas(&M5.Display);

// ---------------------------------------------------------------------------
// Drawing — Pip on his cloud, drawn with M5GFX primitives.
// Pip: round gold-ringed head, sunglasses, black suit, gold tie, on a cloud.
// ---------------------------------------------------------------------------
static void drawPet(int cx, int cy, PetState state, unsigned long now) {
    auto& d = canvas;
    const int W = d.width();
    const int H = d.height();
    const uint16_t navy = d.color565(NAVY_R, NAVY_G, NAVY_B);
    const uint16_t gold = d.color565(GOLD_R, GOLD_G, GOLD_B);
    const uint16_t teal = d.color565(TEAL_R, TEAL_G, TEAL_B);
    const uint16_t white = d.color565(255, 255, 255);
    const uint16_t black = d.color565(0, 0, 0);
    const uint16_t skin = d.color565(255, 205, 160);
    const uint16_t cloudCol = d.color565(220, 232, 245);

    d.fillScreen(navy);

    // Gold bezel ring
    d.drawCircle(cx, cy, (W / 2) - 4, gold);
    d.drawCircle(cx, cy, (W / 2) - 6, gold);

    // Bobbing: gentle in IDLE, quicker while TALKING, still while THINKING.
    float speed = (state == TALKING) ? 0.012f : 0.004f;
    int bob = (state == THINKING) ? 0 : (int)(sinf(now * speed) * 6.0f);
    int px = cx;          // pet centre x
    int py = cy - 40 + bob;  // pet centre y

    // Cloud (three overlapping puffs + a base)
    int cloudY = py + 88;
    d.fillEllipse(cx - 62, cloudY, 58, 26, cloudCol);
    d.fillEllipse(cx, cloudY - 14, 66, 32, cloudCol);
    d.fillEllipse(cx + 62, cloudY, 58, 26, cloudCol);
    d.fillRect(cx - 118, cloudY, 236, 22, cloudCol);

    // Body (black suit) + gold tie
    d.fillRoundRect(px - 34, py + 28, 68, 62, 14, black);
    d.fillTriangle(px - 9, py + 30, px + 9, py + 30, px, py + 62, gold);
    d.fillCircle(px, py + 66, 4, gold);

    // Head
    d.fillCircle(px, py, 40, skin);
    d.drawCircle(px, py, 40, gold);

    // Sunglasses
    d.fillRoundRect(px - 34, py - 14, 30, 18, 6, black);
    d.fillRoundRect(px + 4, py - 14, 30, 18, 6, black);
    d.fillRect(px - 4, py - 8, 8, 4, black);

    // Mouth: smile normally, open "o" while TALKING, flat while THINKING.
    if (state == TALKING) {
        d.fillCircle(px, py + 18, 6, black);
    } else if (state == THINKING) {
        d.fillRect(px - 8, py + 18, 16, 3, black);
    } else {
        d.drawArc(px, py + 6, 14, 12, 20, 160, black);
    }

    // State label + thinking dots
    d.setTextDatum(textdatum_t::middle_center);
    d.setTextColor(teal, navy);
    d.setFont(&fonts::Font4);
    const char* label = "POCKET PIP";
    if (state == LISTENING) label = "LISTENING";
    if (state == THINKING) label = "THINKING";
    if (state == TALKING) label = "PIP SAYS";
    if (state == OFFLINE) label = "NO WI-FI";
    d.drawString(label, cx, 52);

    if (state == THINKING) {
        int dots = (now / 400) % 4;
        for (int i = 0; i < dots; i++) d.fillCircle(cx - 16 + i * 16, 78, 4, gold);
    }

    // Reply text (word-wrapped by hand into short lines near the bottom)
    d.setTextColor(white, navy);
    d.setFont(&fonts::Font2);
    String text = lastReply;
    int lineY = H - 118;
    while (text.length() > 0 && lineY < H - 40) {
        int cut = text.length() <= 26 ? (int)text.length()
                                      : text.lastIndexOf(' ', 26);
        if (cut <= 0) cut = 26;
        d.drawString(text.substring(0, cut), cx, lineY);
        text = text.substring(cut);
        text.trim();
        lineY += 20;
    }

    d.pushSprite(0, 0);
}

// ---------------------------------------------------------------------------
// Chat over Wi-Fi
// ---------------------------------------------------------------------------
static void setState(PetState s) {
    petState = s;
    stateSince = millis();
}

static void sendChat(const String& message) {
    if (WiFi.status() != WL_CONNECTED) {
        setState(OFFLINE);
        lastReply = "No Wi-Fi. Check config.h and the router.";
        return;
    }
    setState(LISTENING);
    drawPet(M5.Display.width() / 2, M5.Display.height() / 2, petState, millis());
    delay(250);

    setState(THINKING);
    HTTPClient http;
    String url = String(PP_BRIDGE_URL) + "/chat";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Pocket-Token", PP_BRIDGE_TOKEN);
    http.setTimeout(65000);

    JsonDocument doc;
    doc["message"] = message;
    String body;
    serializeJson(doc, body);

    int code = http.POST(body);
    if (code == 200) {
        JsonDocument resp;
        if (deserializeJson(resp, http.getString()) == DeserializationError::Ok) {
            lastReply = resp["reply"] | "…";
        } else {
            lastReply = "Got a reply I couldn't read.";
        }
    } else if (code == 401) {
        lastReply = "Bridge rejected my token. Check config.h.";
    } else {
        lastReply = "Bridge didn't answer (HTTP " + String(code) + ").";
    }
    http.end();
    setState(TALKING);
}

// ---------------------------------------------------------------------------
// BLE fallback — feature-flagged OFF by default.
//
// TODO(ble): finish and hardware-verify the BLE path, then flip
// POCKETPIP_ENABLE_BLE to 1 in platformio.ini (env pocket-pip-ble).
// Design: the watch advertises a "PocketPip" GATT service; the phone (or a
// BLE-to-HTTP relay app on the bridge host) writes the user message to the
// MSG characteristic and reads the reply from the REPLY characteristic.
// The skeleton below compiles the advertising half only; the characteristic
// plumbing is deliberately left as a TODO rather than shipping untested code
// that pretends to work.
// ---------------------------------------------------------------------------
#if POCKETPIP_ENABLE_BLE
static const char* kBleServiceUuid = "7e57p1p0-0000-4000-8000-000000000001";  // placeholder, replace before use
static void bleBegin() {
    NimBLEDevice::init("PocketPip");
    NimBLEServer* server = NimBLEDevice::createServer();
    // TODO(ble): create service + MSG/REPLY characteristics, wire to sendChat().
    (void)server;
}
#endif

// ---------------------------------------------------------------------------
static void connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(PP_WIFI_SSID, PP_WIFI_PASSWORD);
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
        delay(250);
    }
    if (WiFi.status() != WL_CONNECTED) setState(OFFLINE);
}

void setup() {
    auto cfg = M5.config();
    M5.begin(cfg);
    M5.Display.setRotation(0);
    canvas.setPsram(true);
    canvas.createSprite(M5.Display.width(), M5.Display.height());
    connectWiFi();
#if POCKETPIP_ENABLE_BLE
    bleBegin();
#endif
    setState(IDLE);
}

void loop() {
    M5.update();
    unsigned long now = millis();

    bool poked = M5.BtnA.wasPressed();
    if (!poked && M5.Display.touch() != nullptr) {
        auto t = M5.Touch.getDetail();
        poked = t.wasPressed();
    }
    if (poked && petState != THINKING && petState != LISTENING) {
        sendChat(kScript[scriptIdx]);
        scriptIdx = (scriptIdx + 1) % kScriptCount;
    }

    // TALKING holds the reply on screen for a few seconds, then back to IDLE.
    if (petState == TALKING && now - stateSince > 5000) setState(IDLE);
    if (petState == OFFLINE && now - stateSince > 5000) {
        connectWiFi();
        if (WiFi.status() == WL_CONNECTED) setState(IDLE);
        else stateSince = now;
    }

    drawPet(M5.Display.width() / 2, M5.Display.height() / 2, petState, now);
    delay(33);  // ~30 fps
}

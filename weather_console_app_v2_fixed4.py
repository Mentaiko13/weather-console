# -*- coding: utf-8 -*-
"""
Weather Console (Flask + Discord Webhook + PWA-ready UI)
- /ui : app-like web UI (PC/iPhone) -> POST /webhook
- /webhook : accepts {"from": "...", "message": "..."} and returns JSON {"reply_text": "..."}
- Posts the same reply to Discord if DISCORD_WEBHOOK_URL is set.

Env:
  OPENWEATHER_API_KEY=...
  DISCORD_WEBHOOK_URL=...   (optional)
  PORT=8787                 (optional)
"""
import os
import re
import json
from datetime import datetime
from typing import Dict, Tuple, Optional, List

import requests
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__)



from flask import redirect

@app.get("/")
def root():
    # Nice-to-have: base URL shows the app instead of 404
    return redirect("/ui", code=302)

@app.get("/favicon.ico")
def favicon():
    # Avoid noisy 404s in logs (optional)
    from flask import send_from_directory
    # If you don't have a favicon, just return 204
    try:
        return send_from_directory(app.static_folder, "favicon.ico")
    except Exception:
        return ("", 204)
# ----------------------------
# Config
# ----------------------------
PORT = int(os.getenv("PORT", "8787"))
OWM_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# Put your common locations here (UI chips will use these keys)
CITY_CHIPS = [
    "横浜", "東京", "箱根", "白馬", "志賀高原", "ガーラ湯沢", "千曲", "船橋", "幕張", "福岡",
    "栂池", "みなとみらい", "保土ヶ谷", "平塚",
]

# Aliases for places that OpenWeather may not resolve well with Japanese query
# Value is a geocoding query string (we'll append ",JP" unless already has country)
CITY_ALIASES: Dict[str, str] = {
    "横浜": "Yokohama",
    "東京": "Tokyo",
    "箱根": "Hakone",
    "白馬": "Hakuba",
    "栂池": "Tsugaike Kogen",
    "志賀高原": "Shiga Kogen",
    "ガーラ湯沢": "GALA Yuzawa",
    "千曲": "Chikuma",
    "船橋": "Funabashi",
    "幕張": "Makuhari",
    "福岡": "Fukuoka",
    "みなとみらい": "Minatomirai Yokohama",
    "保土ヶ谷": "Hodogaya Yokohama",
    "平塚": "Hiratsuka",
}

# ----------------------------
# Helpers
# ----------------------------
def post_to_discord(text: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=10)
        return 200 <= r.status_code < 300
    except Exception:
        return False

def _norm(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("　", " ")
    # remove spaces to allow "東京天気" etc
    s = s.replace(" ", "")
    return s

def parse_command(raw: str) -> Tuple[str, str, str]:
    """
    Returns (intent, city, mode)
      intent: weather | forecast | umbrella | cold | outfit | raw
      mode:   today | forecast | umbrella | cold | outfit | raw
    """
    msg = _norm(raw)
    if not msg:
        return ("raw", "", "raw")

    # intent keywords (order matters)
    if "週間天気" in msg or "週刊天気" in msg or "予報" in msg:
        intent = "forecast"; key = "週間天気"
    elif "傘" in msg or "雨" in msg:
        # "雨" alone is too broad; we still treat as umbrella advice
        intent = "umbrella"; key = "傘"
    elif "寒さ" in msg or "寒い" in msg:
        intent = "cold"; key = "寒さ"
    elif "服装" in msg:
        intent = "outfit"; key = "服装"
    elif "天気" in msg:
        intent = "weather"; key = "天気"
    else:
        # If message is exactly a city chip (e.g., "東京"), default to weather
        if msg in CITY_CHIPS:
            return ("weather", msg, "today")
        return ("raw", msg, "raw")

    # Extract city:
    # Try known chips first (works for "東京天気" "天気東京" "東京週間天気" etc)
    city = ""
    for c in CITY_CHIPS:
        if c in msg:
            city = c
            break

    # If still empty, remove keyword and treat remaining as city
    if not city:
        city = msg.replace(key, "")
        city = city.replace("今日の", "").replace("今日", "")
        city = city.replace("の", "")
        city = city.strip()

    if not city:
        city = "東京"

    mode = {
        "weather": "today",
        "forecast": "forecast",
        "umbrella": "umbrella",
        "cold": "cold",
        "outfit": "outfit",
        "raw": "raw",
    }.get(intent, "raw")

    return (intent, city, mode)

def ow_geo(city: str) -> Optional[Tuple[str, float, float, str]]:
    """
    Resolve city -> (resolved_name, lat, lon, country/region)
    Uses OpenWeather Geocoding API.
    """
    if not OWM_KEY:
        return None

    query = CITY_ALIASES.get(city, city)
    # If already includes country, keep; else add JP to reduce ambiguity
    if "," not in query:
        query = f"{query},JP"

    url = "https://api.openweathermap.org/geo/1.0/direct"
    params = {"q": query, "limit": 5, "appid": OWM_KEY}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None

    best = arr[0]
    name = best.get("name") or city
    lat = best.get("lat")
    lon = best.get("lon")
    country = best.get("country") or ""
    state = best.get("state") or ""
    region = state if state else country
    return (name, float(lat), float(lon), region)

def ow_current(lat: float, lon: float) -> Optional[dict]:
    if not OWM_KEY:
        return None
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"lat": lat, "lon": lon, "units": "metric", "lang": "ja", "appid": OWM_KEY}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    return r.json()

def ow_forecast(lat: float, lon: float) -> Optional[dict]:
    if not OWM_KEY:
        return None
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"lat": lat, "lon": lon, "units": "metric", "lang": "ja", "appid": OWM_KEY}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    return r.json()

def format_today(city_label: str, region: str, w: dict, sender: str) -> str:
    weather = (w.get("weather") or [{}])[0]
    desc = weather.get("description", "不明")
    main = w.get("main") or {}
    wind = w.get("wind") or {}
    temp = main.get("temp")
    feels = main.get("feels_like")
    hum = main.get("humidity")
    ws = wind.get("speed")

    lines = [
        f"【天気】 {city_label} ({region}) (from={sender})",
        f"・状況: {desc}",
        f"・気温: {temp:.1f}℃（体感 {feels:.1f}℃）" if isinstance(temp, (int, float)) and isinstance(feels, (int, float)) else "・気温: 不明",
        f"・湿度: {hum}%" if hum is not None else "・湿度: 不明",
        f"・風: {ws} m/s" if ws is not None else "・風: 不明",
    ]
    return "\n".join(lines)

def summarize_5day(fc: dict) -> List[str]:
    # OpenWeather 3-hour list -> group by date and compute min/max + emoji from noon slot
    items = fc.get("list") or []
    by_date: Dict[str, List[dict]] = {}
    for it in items:
        dt = it.get("dt")
        if not dt:
            continue
        d = datetime.fromtimestamp(dt).strftime("%m/%d")
        by_date.setdefault(d, []).append(it)

    out = []
    for d, arr in list(by_date.items())[:5]:
        temps = [x.get("main", {}).get("temp") for x in arr if isinstance(x.get("main", {}).get("temp"), (int, float))]
        tmin = min(temps) if temps else None
        tmax = max(temps) if temps else None

        # pick one representative weather (closest to 12:00)
        rep = None
        bestdiff = 999999
        for x in arr:
            dt = x.get("dt")
            if not dt:
                continue
            hour = int(datetime.fromtimestamp(dt).strftime("%H"))
            diff = abs(hour - 12)
            if diff < bestdiff:
                bestdiff = diff
                rep = x
        desc = ((rep or {}).get("weather") or [{}])[0].get("main", "")
        emoji = "☀️"
        if "Rain" in desc:
            emoji = "🌧️"
        elif "Snow" in desc:
            emoji = "🌨️"
        elif "Cloud" in desc:
            emoji = "☁️"

        if tmin is not None and tmax is not None:
            out.append(f"・{d} {emoji} {tmin:.1f}℃ / {tmax:.1f}℃")
        else:
            out.append(f"・{d} {emoji}")
    return out

def umbrella_advice(w: dict) -> str:
    # rough: use current weather + precipitation fields
    weather = (w.get("weather") or [{}])[0]
    main = weather.get("main", "")
    pop = None
    if "rain" in (w.get("rain") or {}):
        pop = 1.0
    need = ("Rain" in main) or ("Drizzle" in main) or (pop == 1.0)
    return "傘：必要（雨）" if need else "傘：念のため（今後数日で雨/雪の可能性あり）"

def cold_advice(w: dict) -> str:
    main = w.get("main") or {}
    feels = main.get("feels_like")
    if not isinstance(feels, (int, float)):
        return "寒さ：不明"
    if feels <= 0:
        return "寒さ：かなり寒い（防寒必須）"
    if feels <= 5:
        return "寒さ：寒い（コート＋手袋推奨）"
    if feels <= 10:
        return "寒さ：やや寒い（上着必須）"
    if feels <= 16:
        return "寒さ：ひんやり（薄手の上着）"
    return "寒さ：快適"

def outfit_advice(w: dict) -> str:
    main = w.get("main") or {}
    feels = main.get("feels_like")
    if not isinstance(feels, (int, float)):
        return "服装：不明"
    if feels <= 5:
        return "服装：コート/ダウン + 長袖 + 防寒小物"
    if feels <= 10:
        return "服装：コート/ジャケット + 長袖"
    if feels <= 16:
        return "服装：薄手ジャケット + 長袖"
    if feels <= 22:
        return "服装：長袖 or 羽織り"
    return "服装：半袖寄り"

# ----------------------------
# API Routes
# ----------------------------
@app.get("/ping")
def ping():
    return "pong\n"

@app.post("/webhook")
def webhook():
    # Always return JSON (avoid HTML error pages -> UI JSON parse error)
    try:
        data = request.get_json(silent=True) or {}
        sender = str(data.get("from") or "unknown")
        msg = str(data.get("message") or "").strip()

        intent, city, mode = parse_command(msg)
        # debug log
        print(f"[webhook] from={sender} raw={msg!r} intent={intent} city={city!r} mode={mode}")

        if intent == "raw":
            reply_text = f"[from={sender}] {msg}"
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": city, "reply_text": reply_text})

        geo = ow_geo(city)
        if not geo:
            reply_text = f"場所「{city}」が見つかりませんでした (from={sender})"
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": city, "reply_text": reply_text})

        resolved_name, lat, lon, region = geo

        w = ow_current(lat, lon)
        if not w:
            reply_text = f"天気取得に失敗しました（{resolved_name}） (from={sender})"
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": resolved_name, "reply_text": reply_text})

        if intent == "weather":
            reply_text = format_today(resolved_name, region or "JP", w, sender)
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": resolved_name, "reply_text": reply_text})

        if intent == "forecast":
            fc = ow_forecast(lat, lon)
            if not fc:
                reply_text = f"週間天気取得に失敗しました（{resolved_name}） (from={sender})"
            else:
                lines = [f"【週間天気】 {resolved_name} ({region or 'JP'}) (from={sender})（今後5日）"]
                lines += summarize_5day(fc)
                lines.append("※ OpenWeather無料枠は5日予報が基本です（7日相当はプラン制限のことがあります）")
                reply_text = "\n".join(lines)
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": resolved_name, "reply_text": reply_text})

        if intent in ("umbrella", "cold", "outfit"):
            base = format_today(resolved_name, region or "JP", w, sender)
            extra = []
            if intent == "umbrella":
                extra.append(umbrella_advice(w))
            elif intent == "cold":
                extra.append(cold_advice(w))
            elif intent == "outfit":
                extra.append(outfit_advice(w))
            reply_text = base + "\n・" + "\n・".join(extra)
            sent = post_to_discord(reply_text)
            return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": resolved_name, "reply_text": reply_text})

        # fallback
        reply_text = f"[from={sender}] {msg}"
        sent = post_to_discord(reply_text)
        return jsonify({"status": "ok", "sent_to_discord": sent, "mode": mode, "city": city, "reply_text": reply_text})

    except Exception as e:
        # Return JSON error (so UI can show it safely)
        return jsonify({"status": "error", "error": str(e)}), 500

# ----------------------------
# UI (single-file HTML)
# ----------------------------
UI_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
  <title>Weather Console</title>

  <!-- PWA -->
  <link rel="manifest" href="/static/manifest.json" />
  <meta name="theme-color" content="#0b2b3a" />
  <link rel="apple-touch-icon" href="/static/icons/icon-192.png" />

  <style>
    :root{
      --bg1:#061a23; --bg2:#0a3040; --card:#0c2330cc; --card2:#0b2230aa;
      --text:#eaf6ff; --muted:#b8d5e6;
      --accent:#3aa8ff; --accent2:#5bd0ff;
      --ok:#28d17c; --warn:#ffcc66; --err:#ff6b6b;
      --radius:24px;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans JP", "Helvetica Neue", Arial, "Apple Color Emoji","Segoe UI Emoji";
      color:var(--text);
      min-height:100vh;
      background: radial-gradient(1200px 800px at 20% 10%, #103c55 0%, transparent 60%),
                  radial-gradient(1000px 800px at 85% 20%, #0e4d3c 0%, transparent 55%),
                  linear-gradient(180deg, var(--bg1), var(--bg2));
      padding:18px;
    }
    header{display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px;}
    h1{font-size:44px; letter-spacing:.5px; margin:0; font-weight:800;}
    .sub{color:var(--muted); margin-top:6px; font-size:14px;}
    .pill{
      border:1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.06);
      padding:8px 12px;
      border-radius:999px;
      color:var(--muted);
      font-size:13px;
      display:inline-flex;
      gap:8px;
      align-items:center;
      user-select:none;
    }
    .dot{width:9px;height:9px;border-radius:50%; background:var(--ok); box-shadow:0 0 20px rgba(40,209,124,.5);}
    main{display:grid; grid-template-columns: 1fr 1fr; gap:16px; max-width:1200px;}
    @media (max-width: 900px){ main{grid-template-columns:1fr; } h1{font-size:34px;} }

    .card{
      background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
      border:1px solid rgba(255,255,255,.10);
      border-radius: var(--radius);
      padding:18px;
      box-shadow: 0 20px 60px rgba(0,0,0,.35);
      backdrop-filter: blur(10px);
    }
    .section-title{font-size:22px; font-weight:800; margin:0 0 12px 0;}
    .input{
      width:100%;
      background: rgba(0,0,0,.20);
      border:1px solid rgba(255,255,255,.12);
      color:var(--text);
      border-radius:16px;
      padding:14px 14px;
      font-size:16px;
      outline:none;
    }
    .chips{display:flex; flex-wrap:wrap; gap:10px; margin:12px 0 14px;}
    .chip{
      padding:10px 14px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,.14);
      background: rgba(0,0,0,.18);
      color:var(--text);
      cursor:pointer;
      user-select:none;
      transition:.15s transform, .15s background;
    }
    .chip:hover{transform:translateY(-1px); background: rgba(255,255,255,.10);}
    .btns{display:grid; grid-template-columns: repeat(3, 1fr); gap:12px;}
    @media (max-width: 520px){ .btns{grid-template-columns:1fr 1fr;} }
    .btn{
      padding:14px 14px;
      border-radius:18px;
      border:1px solid rgba(255,255,255,.14);
      background: linear-gradient(180deg, rgba(58,168,255,.85), rgba(58,168,255,.55));
      color:#001018;
      font-weight:800;
      cursor:pointer;
      transition:.15s transform, .15s filter;
      box-shadow: 0 12px 30px rgba(58,168,255,.20);
    }
    .btn.secondary{background: rgba(0,0,0,.18); color:var(--text); box-shadow:none;}
    .btn:hover{transform:translateY(-1px); filter:brightness(1.04);}
    .row{display:flex; gap:12px; flex-wrap:wrap; margin-top:12px;}
    .hint{margin-top:10px; color:var(--muted); font-size:13px; line-height:1.4;}
    .result{
      min-height:260px;
      white-space:pre-wrap;
      background: rgba(0,0,0,.18);
      border:1px solid rgba(255,255,255,.12);
      border-radius:18px;
      padding:14px;
      overflow:auto;
      font-size:14px;
    }
    .toolbar{display:flex; gap:10px; justify-content:flex-end; flex-wrap:wrap; margin-bottom:10px;}
    .smallbtn{
      padding:10px 12px;
      border-radius:14px;
      border:1px solid rgba(255,255,255,.14);
      background: rgba(0,0,0,.18);
      color:var(--text);
      font-weight:700;
      cursor:pointer;
    }
    .status{margin-top:10px; font-size:13px;}
    .status.ok{color:var(--ok);}
    .status.err{color:var(--err);}
    .kbd{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      background: rgba(255,255,255,.08);
      border:1px solid rgba(255,255,255,.12);
      padding:2px 6px;
      border-radius:8px;
      color:var(--muted);
    }
  
  /* --- UX polish (tap feel / loading / offline) --- */
  .btn, .chip, .action {
    transition: transform 0.08s ease, filter 0.15s ease, opacity 0.15s ease;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
  }
  .btn:active, .chip:active, .action:active { transform: scale(0.98); filter: brightness(0.98); }
  .btn[disabled], .chip[disabled], .action[disabled] { opacity: 0.55; pointer-events: none; }

  .net-banner{
    max-width: 980px;
    margin: 10px auto 0;
    padding: 10px 14px;
    border-radius: 14px;
    background: rgba(255, 204, 0, 0.18);
    border: 1px solid rgba(255, 204, 0, 0.35);
    color: rgba(20,20,20,0.9);
    font-weight: 600;
  }
  .hidden{ display:none !important; }

  .loading{
    position: fixed;
    inset: 0;
    display:flex;
    align-items:center;
    justify-content:center;
    background: rgba(0,0,0,0.18);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    z-index: 9999;
  }
  .loading-card{
    background: rgba(255,255,255,0.92);
    border: 1px solid rgba(0,0,0,0.08);
    box-shadow: 0 18px 50px rgba(0,0,0,0.18);
    border-radius: 18px;
    padding: 16px 18px;
    display:flex;
    gap: 12px;
    align-items:center;
  }
  .spinner{
    width: 18px;
    height: 18px;
    border-radius: 999px;
    border: 3px solid rgba(0,0,0,0.15);
    border-top-color: rgba(0,0,0,0.55);
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-text{ font-weight: 700; }

</style>
</head>
<body>
<header>
  <div>
    <h1>Weather Console</h1>
    <div class="sub">iPhoneから “アプリっぽく” /webhook を叩くUI（Discordにも投稿されます）</div>
  </div>
  <div class="pill"><span class="dot"></span><span id="readyText">Ready</span></div>
</header>
  <div id="netBanner" class="net-banner hidden">📴 オフラインです（通信できないため実行できません）</div>

  <div id="loadingOverlay" class="loading hidden" aria-hidden="true">
    <div class="loading-card">
      <div class="spinner" aria-hidden="true"></div>
      <div class="loading-text">通信中…</div>
    </div>
  </div>


<main>
  <section class="card">
    <div class="section-title">コマンド入力</div>
    <input id="cmd" class="input" placeholder="例：横浜天気 / 東京週間天気 / 横浜服装 / 千曲傘" />
    <div class="chips" id="chips"></div>

    <div class="btns">
      <button class="btn" onclick="sendPreset('today')">今日の天気</button>
      <button class="btn" onclick="sendPreset('forecast')">週間天気</button>
      <button class="btn" onclick="sendPreset('umbrella')">傘いる？</button>
      <button class="btn" onclick="sendPreset('cold')">寒さ</button>
      <button class="btn" onclick="sendPreset('outfit')">服装</button>
      <button class="btn secondary" onclick="sendRaw()">そのまま送信</button>
    </div>

    <div class="row">
      <button class="smallbtn" onclick="startVoice()">🎤 音声入力（ブラウザ対応時）</button>
      <button class="smallbtn" onclick="clearAll()">クリア</button>
    </div>

    <div class="hint">
      コツ：都市チップ→ボタンで <span class="kbd">横浜天気</span> のように自動生成できます（スペース無しでもOK）<br/>
      ※ iPhoneの「ショートカット音声入力」でもOK（作ったやつと同じ思想です）
    </div>
  </section>

  <section class="card">
    <div class="toolbar">
      <button class="smallbtn" onclick="speak()">🔊 読み上げ</button>
      <button class="smallbtn" onclick="copyText()">📋 コピー</button>
    </div>
    <div class="section-title">結果</div>
    <div id="result" class="result">ここに結果が表示されます。</div>
    <div id="status" class="status ok">待機中</div>
  </section>
</main>

<script>
// --- helper: always call this app's /webhook on the same origin ---
function getWebhookUrl(){
  // If you opened ui.html via file://, fetch will fail. Use http://<PC-IP>:8787/ui instead.
  if (location.protocol === 'file:') {
    return null;
  }
  return location.origin + "/webhook";
}

const CITY_CHIPS = %CITY_JSON%;

const chipsEl = document.getElementById('chips');
const cmdEl = document.getElementById('cmd');
const resultEl = document.getElementById('result');
const statusEl = document.getElementById('status');

const netBannerEl = document.getElementById('netBanner');
const loadingOverlayEl = document.getElementById('loadingOverlay');

/** show/hide the full-screen loading overlay */
function setLoading(on){
  if(!loadingOverlayEl) return;
  loadingOverlayEl.classList.toggle('hidden', !on);
  loadingOverlayEl.setAttribute('aria-hidden', on ? 'false' : 'true');
}

/** show/hide offline banner */
function setNetBanner(show){
  if(!netBannerEl) return;
  netBannerEl.classList.toggle('hidden', !show);
}


let selectedCity = "";

function renderChips(){
  chipsEl.innerHTML = "";
  CITY_CHIPS.forEach(c=>{
    const b = document.createElement('button');
    b.className = "chip";
    b.textContent = c;
    b.onclick = ()=>{ selectedCity = c; cmdEl.value = c; };
    chipsEl.appendChild(b);
  });
}
renderChips();

async function postWebhook(message){
  // オフライン判定（PWAでもわかりやすく）
  if(!navigator.onLine){
    netBannerEl.classList.remove('hidden');
    statusEl.className = "status err";
    statusEl.textContent = "失敗：オフラインです";
    resultEl.textContent = "ネット接続がないため実行できません。オンラインになってから再実行してください。";
    return;
  }

  // loading on
  setLoading(true);
  netBannerEl.classList.add('hidden');
  statusEl.className = "status ok";
  statusEl.textContent = "送信中...";
  resultEl.textContent = "…";

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 12000); // 12s timeout

  try{
    const endpoint = getWebhookUrl();
      const res = await fetch(endpoint, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({from:'ui', message}),
      signal: controller.signal
    });
    clearTimeout(t);

    // JSON以外(HTMLエラー等)が返ったときも読めるようにする
    const ct = (res.headers.get('content-type') || '').toLowerCase();
    let data = null;
    if(ct.includes('application/json')){
      data = await res.json();
    }else{
      const raw = await res.text();
      data = { status: res.ok ? "ok" : "error", reply_text: raw, raw };
    }

    if(!res.ok || data.status === "error"){
      const msg = data.reply_text || data.error || ("HTTP " + res.status);
      resultEl.textContent = "ERROR: " + msg + (data.raw ? ("\n\n" + String(data.raw).slice(0,800)) : "");
      statusEl.className = "status err";
      statusEl.textContent = "失敗：エラー";
      return;
    }

    resultEl.textContent = data.reply_text || JSON.stringify(data, null, 2);
    statusEl.className = "status ok";
    statusEl.textContent = "成功：UIに表示 + Discordにも投稿済み";
  }catch(e){
    const msg = (e && e.name === "AbortError") ? "タイムアウトしました（12秒）" : String(e);
    resultEl.textContent = "ERROR: " + msg;
    statusEl.className = "status err";
    statusEl.textContent = "失敗：通信エラー（/webhook）";
  }finally{
    setLoading(false);
  }
}

function sendPreset(kind){
  const city = cmdEl.value.trim() || selectedCity || "東京";
  const msgMap = {
    today: city + "天気",
    forecast: city + "週間天気",
    umbrella: city + "傘",
    cold: city + "寒さ",
    outfit: city + "服装",
  };
  postWebhook(msgMap[kind] || city);
}

function sendRaw(){
  const city = cmdEl.value.trim() || selectedCity || "";
  postWebhook(city);
}

function clearAll(){
  cmdEl.value = "";
  selectedCity = "";
  resultEl.textContent = "ここに結果が表示されます。";
  statusEl.className = "status ok";
  statusEl.textContent = "待機中";
}

function copyText(){
  navigator.clipboard.writeText(resultEl.textContent || "");
  statusEl.textContent = "コピーしました";
}

function speak(){
  const txt = resultEl.textContent || "";
  if(!txt) return;
  const u = new SpeechSynthesisUtterance(txt);
  u.lang = 'ja-JP';
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

function startVoice(){
  // Web Speech API (Chrome etc). Safari iOS may be limited.
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    alert("このブラウザは音声認識が未対応です。iPhoneはショートカットの音声入力が確実です。");
    return;
  }
  const rec = new SR();
  rec.lang = 'ja-JP';
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (e)=>{
    const t = e.results[0][0].transcript;
    cmdEl.value = t.replace(/\s+/g,'');
    statusEl.textContent = "音声入力完了";
  };
  rec.onerror = ()=> statusEl.textContent = "音声入力エラー";
  rec.start();
  statusEl.textContent = "音声入力中...";
}

// Register Service Worker (PWA)
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/static/sw.js').catch(()=>{});
}

window.addEventListener('online',  () => setNetBanner(false));
window.addEventListener('offline', () => setNetBanner(true));

</script>
</body>
</html>
"""

@app.get("/ui")
def ui():
    html = UI_HTML.replace("%CITY_JSON%", json.dumps(CITY_CHIPS, ensure_ascii=False))
    return Response(html, mimetype="text/html; charset=utf-8")

# ----------------------------
# Static files for PWA
# ----------------------------
@app.get("/static/<path:filename>")
def static_files(filename: str):
    # expects you created ./static next to this script
    base = os.path.join(os.path.dirname(__file__), "static")
    return send_from_directory(base, filename)

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    if not OWM_KEY:
        print("[WARN] OPENWEATHER_API_KEY is not set. Weather features will fail.")
    app.run(host="0.0.0.0", port=PORT, debug=False)
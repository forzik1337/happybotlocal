from twitchio.ext import commands
from flask import Flask, request, jsonify
import requests
import asyncio
import threading
import time
import json
import os

# =========================
# АЛИАСЫ
# =========================

GAME_ALIASES = {
    "cs": "Counter-Strike",
    "cs2": "Counter-Strike",
    "csgo": "Counter-Strike",
    "counter strike": "Counter-Strike",
    "jc": "just chatting"
}

# =========================
# НАСТРОЙКИ
# =========================
TOKEN = os.environ.get("TOKEN")
CHANNEL = "mixarage"
CLIENT_ID = os.environ.get("CLIENT_ID")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
BROADCASTER_ID = os.environ.get("BROADCASTER_ID")

SETTINGS_FILE = "settings.json"

# =========================
# DEFAULT VALUES
# =========================
auto_enabled = True

# Список авто-сообщений: каждый элемент — {"message": "...", "interval": 1800}
auto_messages = [
    {
        "message": "LO LOL ChickenGunGuitar <--- НЕ ВИДИШЬ СМАЙЛИКИ? ТОГДА ПРОСТО СКАЧАЙ НА ПК РАСШИРЕНИЕ 7tv - 7tv.app ИЛИ НА ТЕЛЕФОН ПРИЛОЖЕНИЕ frosty",
        "interval": 30 * 60
    },
    {
        "message": "ТГ ТЕЛЕГРАММ КАНАЛ УБЛЮДКААААААА - https://t.me/mixarage",
        "interval": 60 * 60
    }
]


# =========================
# SAVE / LOAD
# =========================
def save_settings():
    data = {
        "auto_enabled": auto_enabled,
        "auto_messages": auto_messages
    }
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_settings():
    global auto_enabled, auto_messages

    if not os.path.exists(SETTINGS_FILE):
        return

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    auto_enabled = data.get("auto_enabled", auto_enabled)

    # Поддержка старого формата (auto1_message / auto2_message)
    if "auto_messages" in data:
        auto_messages = data["auto_messages"]
    else:
        auto_messages.clear()
        if "auto1_message" in data:
            auto_messages.append({
                "message": data["auto1_message"],
                "interval": data.get("auto1_interval", 30 * 60)
            })
        if "auto2_message" in data:
            auto_messages.append({
                "message": data["auto2_message"],
                "interval": data.get("auto2_interval", 60 * 60)
            })


load_settings()

# =========================
# ПОСЛЕДНЯЯ СТАВКА
# =========================
last_prediction = None  # {"title": "...", "outcomes": ["Да", "Нет"], "duration": 120}


def get_headers():
    return {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }


def create_prediction(title, outcomes, duration=120):
    """Создаёт Twitch Prediction. Возвращает (True, prediction_id) или (False, error)."""
    body = {
        "broadcaster_id": BROADCASTER_ID,
        "title": title,
        "outcomes": [{"title": o} for o in outcomes],
        "prediction_window": duration
    }
    r = requests.post(
        "https://api.twitch.tv/helix/predictions",
        headers=get_headers(),
        json=body
    )
    if r.status_code == 200:
        pred_id = r.json()["data"][0]["id"]
        return True, pred_id
    return False, r.text


def get_active_prediction_id(include_locked=False):
    """Возвращает ID активной (и опционально залоченной) ставки."""
    statuses = ["ACTIVE", "LOCKED"] if include_locked else ["ACTIVE"]
    for status in statuses:
        r = requests.get(
            "https://api.twitch.tv/helix/predictions",
            headers=get_headers(),
            params={"broadcaster_id": BROADCASTER_ID, "first": 1, "status": status}
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                return data[0]["id"]
    return None


def get_last_ended_prediction():
    """Получает последнюю завершённую/отменённую ставку с Twitch."""
    r = requests.get(
        "https://api.twitch.tv/helix/predictions",
        headers=get_headers(),
        params={"broadcaster_id": BROADCASTER_ID, "first": 1}
    )
    if r.status_code != 200:
        return None
    data = r.json().get("data", [])
    if not data:
        return None
    pred = data[0]
    return {
        "title": pred["title"],
        "outcomes": [o["title"] for o in pred["outcomes"]],
        "duration": pred["prediction_window"]
    }


# =========================
# TWITCH BOT
# =========================
class Bot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=TOKEN,
            prefix="!",
            initial_channels=[CHANNEL]
        )

    async def event_ready(self):
        print("Бот запущен:", self.nick)

    # =========================
    # !title
    # =========================
    @commands.command()
    async def title(self, ctx, *, new_title):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        url = f"https://api.twitch.tv/helix/channels?broadcaster_id={BROADCASTER_ID}"
        r = requests.patch(url, headers=headers, json={"title": new_title})

        if r.status_code == 204:
            await ctx.send(f"📝 Название стрима изменено: {new_title}")
        else:
            await ctx.send("❌ Ошибка названия")

    # =========================
    # !game
    # =========================
    @commands.command()
    async def game(self, ctx, *, game_name):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        query = GAME_ALIASES.get(game_name.lower(), game_name)
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }
        r = requests.get(
            "https://api.twitch.tv/helix/games",
            headers=headers,
            params={"name": query}
        )

        if r.status_code != 200:
            await ctx.send("❌ Twitch API ошибка")
            return

        data = r.json().get("data", [])
        if not data:
            await ctx.send("❌ Игра не найдена")
            return

        game = data[0]
        game_id = game["id"]
        real_name = game["name"]

        r2 = requests.patch(
            f"https://api.twitch.tv/helix/channels?broadcaster_id={BROADCASTER_ID}",
            headers=headers,
            json={"game_id": game_id}
        )

        if r2.status_code == 204:
            await ctx.send(f"🎮 Категория была изменена: {real_name}")
        else:
            await ctx.send("❌ Ошибка смены игры")

    # =========================
    # !tg / !tt / !donate
    # =========================
    @commands.command()
    async def tg(self, ctx):
        await ctx.send("📢 Новости о стримах тут https://t.me/mixarage")

    @commands.command()
    async def tt(self, ctx):
        await ctx.send("🎵 Нарезки: nertizxyecoc, Мой тик ток: xyecoc037")

    @commands.command()
    async def donate(self, ctx):
        await ctx.send("💰 Денег много сюда: https://www.donationalerts.com/r/mopsyara009")

    @commands.command()
    async def алабуга(self, ctx):
        await ctx.send("📢 Новости о стримах тут https://t.me/mixarage")

    @commands.command()
    async def win(self, ctx):
        await ctx.send("win1 win2 win3 — 67p ПО ПРОМОКОДУ \"MixaRage\" ПЕРЕХОДИ НА ЛУЧШЕГО БУКМЕЙКЕРА РОССИИ WINLINE — https://t.me/mixarage")

    @commands.command()
    async def winline(self, ctx):
        await ctx.send("win1 win2 win3 — 67p ПО ПРОМОКОДУ \"MixaRage\" ПЕРЕХОДИ НА ЛУЧШЕГО БУКМЕЙКЕРА РОССИИ WINLINE — https://t.me/mixarage")

    # =========================
    # !clospred — закрыть приём ставок (LOCKED)
    # =========================
    @commands.command()
    async def clospred(self, ctx):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        pred_id = get_active_prediction_id()
        if not pred_id:
            await ctx.send("❌ Нет активной ставки")
            return

        r = requests.patch(
            "https://api.twitch.tv/helix/predictions",
            headers=get_headers(),
            json={"broadcaster_id": BROADCASTER_ID, "id": pred_id, "status": "LOCKED"}
        )
        if r.status_code == 200:
            await ctx.send("🔒 Приём баллов тютюн")
        else:
            await ctx.send(f"❌ Ошибка: {r.text[:100]}")

    # =========================
    # !pred <вариант> — выбрать победивший исход
    # =========================
    @commands.command()
    async def pred(self, ctx, *, outcome_title):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        # Получаем активную/залоченную ставку
        r = requests.get(
            "https://api.twitch.tv/helix/predictions",
            headers=get_headers(),
            params={"broadcaster_id": BROADCASTER_ID, "first": 1, "status": "LOCKED"}
        )
        # Если залоченной нет — пробуем активную
        if r.status_code != 200 or not r.json().get("data"):
            r = requests.get(
                "https://api.twitch.tv/helix/predictions",
                headers=get_headers(),
                params={"broadcaster_id": BROADCASTER_ID, "first": 1, "status": "ACTIVE"}
            )

        if r.status_code != 200:
            await ctx.send("❌ Нет активной ставки")
            return

        data = r.json().get("data", [])
        if not data:
            await ctx.send("❌ Нет активной ставки")
            return

        pred_data = data[0]
        pred_id = pred_data["id"]
        outcomes = pred_data["outcomes"]

        # Ищем исход по названию (без учёта регистра)
        winning = None
        for o in outcomes:
            if outcome_title.lower() in o["title"].lower():
                winning = o
                break

        if not winning:
            names = " / ".join(o["title"] for o in outcomes)
            await ctx.send(f"❌ Вариант не найден. Доступные: {names}")
            return

        r2 = requests.patch(
            "https://api.twitch.tv/helix/predictions",
            headers=get_headers(),
            json={
                "broadcaster_id": BROADCASTER_ID,
                "id": pred_id,
                "status": "RESOLVED",
                "winning_outcome_id": winning["id"]
            }
        )
        if r2.status_code == 200:
            await ctx.send(f"✅ Победил вариант: «{winning['title']}»! Баллы розданы.")
        else:
            await ctx.send(f"❌ Ошибка: {r2.text[:100]}")

    # =========================
    # !delpred — отменить ставку и вернуть баллы
    # =========================
    @commands.command()
    async def delpred(self, ctx):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        pred_id = get_active_prediction_id(include_locked=True)
        if not pred_id:
            await ctx.send("❌ Нет активной ставки")
            return

        r = requests.patch(
            "https://api.twitch.tv/helix/predictions",
            headers=get_headers(),
            json={"broadcaster_id": BROADCASTER_ID, "id": pred_id, "status": "CANCELED"}
        )
        if r.status_code == 200:
            await ctx.send("🗑 Ставка отменена, баллы возвращены!")
        else:
            await ctx.send(f"❌ Ошибка: {r.text[:100]}")

    # =========================
    # !repred — пересоздать последнюю ставку
    # =========================
    @commands.command()
    async def repred(self, ctx):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        global last_prediction

        # Сначала пробуем взять из памяти, если нет — тянем с Twitch API
        pred = last_prediction or get_last_ended_prediction()

        if not pred:
            await ctx.send("❌ Не найдено ни одной предыдущей ставки")
            return

        ok, result = create_prediction(pred["title"], pred["outcomes"], pred["duration"])

        if ok:
            last_prediction = pred
            outcomes_str = " / ".join(pred["outcomes"])
            await ctx.send(f"🔁 Ставка пересоздана: «{pred['title']}» ({outcomes_str})")
        else:
            await ctx.send(f"❌ Ошибка создания ставки: {result}")


# =========================
# FLASK
# =========================
app = Flask(__name__)


@app.route("/")
def home():
    return """
    <html>
    <head>
        <title>Twitch Panel</title>
        <meta charset="UTF-8">
        <style>
        body {
            margin: 0;
            background: #0f0f0f;
            color: white;
            font-family: sans-serif;
            text-align: center;
            padding-top: 30px;
        }
        h1 { margin-bottom: 20px; }
        .btn {
            width: 200px; height: 120px; font-size: 18px;
            border: none; border-radius: 20px; cursor: pointer;
            color: white; margin: 10px; transition: 0.15s;
        }
        .btn:active { transform: scale(0.95); filter: brightness(1.2); }
        .tg { background: #0088cc; }
        .smile { background: #ff4d6d; }
        .panel { margin-top: 10px; }
        .auto-section {
            margin-top: 30px; display: inline-block;
            background: #1a1a1a; padding: 20px; border-radius: 15px;
            min-width: 500px;
        }
        input[type=text], textarea {
            padding: 8px; width: 340px; margin: 5px;
            border-radius: 8px; border: none;
            background: #2a2a2a; color: white; font-size: 13px;
        }
        input[type=number] {
            padding: 8px; width: 80px; margin: 5px;
            border-radius: 8px; border: none;
            background: #2a2a2a; color: white;
        }
        .smallBtn {
            padding: 8px 14px; border: none; border-radius: 10px;
            cursor: pointer; background: #2ecc71; color: white; margin: 3px;
            font-size: 13px;
        }
        .delBtn {
            padding: 8px 14px; border: none; border-radius: 10px;
            cursor: pointer; background: #e74c3c; color: white; margin: 3px;
            font-size: 13px;
        }
        .addBtn {
            margin-top: 15px; padding: 12px 25px; border-radius: 12px;
            border: 2px dashed #555; cursor: pointer; background: transparent;
            color: #aaa; font-size: 16px; transition: 0.2s; width: 100%;
        }
        .addBtn:hover { border-color: #2ecc71; color: #2ecc71; }
        .toggle {
            margin-top: 15px; padding: 10px 20px; border-radius: 10px;
            border: none; cursor: pointer; background: #e74c3c; color: white;
            font-size: 15px;
        }
        #status {
            position: fixed; top: 20px; right: 20px; padding: 10px;
            background: #e74c3c; border-radius: 10px; font-weight: bold;
        }
        .auto-item {
            background: #222; border-radius: 12px; padding: 12px;
            margin: 10px 0; display: flex; align-items: center;
            gap: 8px; flex-wrap: wrap; justify-content: center;
        }
        .auto-num {
            font-weight: bold; color: #aaa; min-width: 30px;
        }
        .btn-gif { width: 200px; height: 120px; border-radius: 20px; border: none; cursor: pointer; position: relative; overflow: hidden; color: white; font-weight: bold; }
        .btn-gif span { position: relative; z-index: 2; text-shadow: 0 0 6px black; }
        .btn-gif::before { content: ""; position: absolute; inset: 0; background-size: cover; background-position: center; filter: brightness(0.7); }
        .btn-gif:active { transform: scale(0.95); }
        button[onclick*="tg"]::before { background-image: url("https://cdn.7tv.app/emote/01K5Y2ZB2Q7GYJGBFCSXK4S422/4x.avif"); }
        button[onclick*="smile"]::before { background-image: url("https://cdn.7tv.app/emote/01HS92S040000DP2RP0GR0ZDZZ/4x.avif"); }
        .corner-img { position: fixed; right: 20px; bottom: 20px; width: 160px; height: auto; border-radius: 12px; box-shadow: 0 0 20px rgba(0,0,0,0.5); z-index: 9999; pointer-events: none; }
        .tg-box { position: fixed; left: 20px; bottom: 20px; z-index: 9999; text-align: center; }
        .tg-label { color: white; margin-bottom: 8px; font-size: 16px; font-weight: bold; }
        .tg-corner { width: 90px; height: 90px; object-fit: cover; border-radius: 20px; box-shadow: 0 0 25px rgba(0,136,204,0.8); cursor: pointer; transition: 0.2s; }
        .tg-corner:hover { transform: scale(1.08); }
        .social-bar { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); display: flex; gap: 18px; z-index: 9999; }
        .social-icon { width: 70px; height: 70px; object-fit: cover; border-radius: 18px; cursor: pointer; transition: 0.2s; background: white; padding: 8px; box-shadow: 0 0 20px rgba(0,0,0,0.4); }
        .tg-icon { box-shadow: 0 0 25px rgba(0,136,204,0.8); }
        .gpt-icon { box-shadow: 0 0 25px rgba(16,163,127,0.8); }
        .yt-icon { box-shadow: 0 0 25px rgba(255,0,0,0.8); }
        .twitch-icon { box-shadow: 0 0 25px rgba(145,70,255,0.8); }
        .social-icon:hover { transform: scale(1.12); }
        .donate::before { content: ""; position: absolute; inset: 0; background: url("https://cdn.7tv.app/emote/01GBFAYKGR000FWWN7MDZZ8XQN/4x.avif"); background-size: cover; background-position: center; }
        .top-left-gif { position: fixed; top: 20px; left: 20px; width: 320px; height: auto; border-radius: 18px; z-index: 9999; pointer-events: none; }
        .local-site-btn { position: fixed; top: 20px; left: 340px; width: 120px; height: 120px; border-radius: 20px; object-fit: cover; z-index: 99999; cursor: pointer; box-shadow: 0 0 25px rgba(0,255,120,0.7); transition: 0.2s; }
        .local-site-btn:hover { transform: scale(1.08); }
        .gif-bet { position: relative; width: 200px; height: 120px; border-radius: 20px; overflow: hidden; cursor: pointer; border: none; }
        .gif-bet::before { content: ""; position: absolute; inset: 0; background: url("https://media1.tenor.com/m/YXMkqSh7Y4gAAAAd/gamba.gif"); background-size: cover; background-position: center; }
        .gif-bet::after { content: ""; position: absolute; inset: 0; background: rgba(0,0,0,0.4); }
        .gif-bet span { position: relative; color: white; z-index: 1; font-weight: bold; font-size: 16px; }
        </style>
    </head>
    <body>
    <h1>СТРИМ ПАНЕЛЬ 😎🤙</h1>
    <div class="panel">
        <button class="btn-gif tg" onclick="send('tg')"><span>ТЕЛЕГРАМ</span></button>
        <button class="btn-gif smile" onclick="send('smile')"><span>СМАЙЛЫ</span></button>
        <button class="btn gif-bet" onclick="send('bet_start')"><span>СТАРТ СТАВКИ</span></button>
        <button class="btn-gif donate" onclick="send('donate')"><span>ДОНАТ</span></button>
        <img src="https://i.ibb.co/PZRnvpgg/sample-2a24be18c3db1a3b27063ec6b718f7b1.png" class="corner-img">
        <div class="tg-box">
            <div class="tg-label">Тгк крутешего</div>
            <a href="https://t.me/ZZZZZkruteyshiy" target="_blank">
                <img src="https://i.ibb.co/hFMSr71D/photo-2026-05-14-21-30-44.jpg" class="tg-corner">
            </a>
        </div>
        <div class="social-bar">
            <a href="https://t.me/forzikxDSvin" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg" class="social-icon tg-icon"></a>
            <a href="https://chatgpt.com" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg" class="social-icon gpt-icon"></a>
            <a href="https://youtube.com" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/e/ef/Youtube_logo.png" class="social-icon yt-icon"></a>
            <a href="https://twitch.tv/forzikxd" target="_blank"><img src="https://i.ibb.co/3m6BxbZ2/image-2.png" class="social-icon twitch-icon"></a>
        </div>
        <img src="https://i.ibb.co/5hYCCKWc/video.gif" class="top-left-gif">
        <a href="http://127.0.0.1:3000" target="_blank">
            <img src="https://i.ibb.co/hFMSr71D/photo-2026-05-14-21-30-44.jpg" class="local-site-btn">
        </a>
    </div>

    <div class="auto-section">
        <h2>⚙️ АВТО СООБЩЕНИЯ</h2>
        <div id="autoList"></div>
        <button class="addBtn" onclick="addAuto()">+ Добавить авто сообщение</button>
        <br>
        <button class="toggle" onclick="toggle()">ON / OFF AUTO</button>
    </div>

    <div id="status">...</div>

    <script>
    let autos = [];

    async function loadAutos() {
        const r = await fetch('/get_autos');
        const data = await r.json();
        autos = data.auto_messages;
        const enabled = data.auto_enabled;
        const s = document.getElementById("status");
        if (enabled) { s.innerHTML = "ON"; s.style.background = "#2ecc71"; }
        else { s.innerHTML = "OFF"; s.style.background = "#e74c3c"; }
        renderList();
    }

    function renderList() {
        const container = document.getElementById("autoList");
        container.innerHTML = "";
        autos.forEach((a, i) => {
            const div = document.createElement("div");
            div.className = "auto-item";
            div.innerHTML = `
                <span class="auto-num">#${i+1}</span>
                <input type="text" id="msg_${i}" value="${escHtml(a.message)}" placeholder="Текст сообщения" style="width:280px">
                <input type="number" id="int_${i}" value="${Math.round(a.interval / 60)}" min="1" style="width:70px" title="Интервал в минутах">
                <span style="color:#aaa;font-size:12px">мин</span>
                <button class="smallBtn" onclick="saveAuto(${i})">💾</button>
                <button class="delBtn" onclick="deleteAuto(${i})">🗑</button>
            `;
            container.appendChild(div);
        });
    }

    function escHtml(str) {
        return str.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }

    async function saveAuto(i) {
        const msg = document.getElementById("msg_" + i).value;
        const mins = parseInt(document.getElementById("int_" + i).value) || 30;
        autos[i] = { message: msg, interval: mins * 60 };
        await fetch('/save_autos', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ auto_messages: autos })
        });
        alert("✅ Авто #" + (i+1) + " сохранено!");
    }

    async function deleteAuto(i) {
        if (!confirm("Удалить авто #" + (i+1) + "?")) return;
        autos.splice(i, 1);
        await fetch('/save_autos', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ auto_messages: autos })
        });
        renderList();
    }

    async function addAuto() {
        autos.push({ message: "Новое авто сообщение", interval: 30 * 60 });
        await fetch('/save_autos', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ auto_messages: autos })
        });
        renderList();
        // Скроллим вниз к новому
        const items = document.querySelectorAll('.auto-item');
        if (items.length) items[items.length-1].scrollIntoView({behavior:'smooth'});
    }

    async function send(t) { await fetch('/send/' + t); }

    async function toggle() {
        const r = await fetch('/toggle_auto');
        const t = await r.text();
        const s = document.getElementById("status");
        if (t === "True") { s.innerHTML = "ON"; s.style.background = "#2ecc71"; }
        else { s.innerHTML = "OFF"; s.style.background = "#e74c3c"; }
    }

    loadAutos();
    </script>
    </body>
    </html>
    """


# =========================
# КНОПКИ
# =========================
@app.route("/send/<action>")
def send(action):
    if action == "tg":
        msg = auto_messages[1]["message"] if len(auto_messages) > 1 else "https://t.me/mixarage"
    elif action == "smile":
        msg = auto_messages[0]["message"] if len(auto_messages) > 0 else "..."
    elif action == "bet_start":
        msg = "СТАВКА НАЧАЛАСЬ❗❗❗"
        async def spam():
            await send_message(msg)
            await asyncio.sleep(0.8)
            await send_message(msg)
            await asyncio.sleep(0.8)
            await send_message(msg)
        asyncio.run_coroutine_threadsafe(spam(), bot.loop)
        return "OK"
    elif action == "donate":
        msg = "DONALERT ЗАДОНАТИТЬ ТИПОЧКУ - https://www.donationalerts.com/r/mopsyara009"
    else:
        msg = "..."

    asyncio.run_coroutine_threadsafe(send_message(msg), bot.loop)
    return "OK"


# =========================
# API ROUTES ДЛЯ АВТО
# =========================
@app.route("/get_autos")
def get_autos():
    return jsonify({
        "auto_enabled": auto_enabled,
        "auto_messages": auto_messages
    })


@app.route("/save_autos", methods=["POST"])
def save_autos_route():
    global auto_messages
    data = request.get_json()
    auto_messages = data.get("auto_messages", auto_messages)
    save_settings()
    return "OK"


@app.route("/toggle_auto")
def toggle_auto():
    global auto_enabled
    auto_enabled = not auto_enabled
    save_settings()
    return str(auto_enabled)

# =========================
# ПРОВЕРКА СТРИМА
# =========================
def is_stream_live():
    r = requests.get(
        "https://api.twitch.tv/helix/streams",
        headers=get_headers(),
        params={"user_id": BROADCASTER_ID}
    )
    if r.status_code != 200:
        return False
    return len(r.json().get("data", [])) > 0


def stream_watcher():
    global auto_enabled
    was_live = False

    while True:
        time.sleep(60)  # проверяем каждую минуту

        live = is_stream_live()

        if live and not was_live:
            auto_enabled = True
            save_settings()
            print("[stream] Стрим начался — авто включены")

        elif not live and was_live:
            auto_enabled = False
            save_settings()
            print("[stream] Стрим закончился — авто выключены")

        was_live = live
# =========================
# AUTO LOOP
# =========================
def auto_loop():
    last_sent = {}
    last_any_message = 0

    while True:
        time.sleep(1)

        if not auto_enabled:
            continue

        now = time.time()

        # Найти сообщение которое дольше всего ждёт отправки
        best_i = None
        best_overdue = -1

        for i, entry in enumerate(auto_messages):
            msg = entry.get("message", "")
            interval = entry.get("interval", 30 * 60)
            if not msg:
                continue

            if i not in last_sent:
                last_sent[i] = now
                continue

            overdue = (now - last_sent[i]) - interval
            if overdue >= 0 and overdue > best_overdue:
                best_overdue = overdue
                best_i = i

        # Отправляем только одно — самое "просроченное"
        if best_i is not None:
            last_sent[best_i] = now
            asyncio.run_coroutine_threadsafe(
                send_message(auto_messages[best_i]["message"]),
                bot.loop
            )

        for k in list(last_sent.keys()):
            if k >= len(auto_messages):
                del last_sent[k]


# =========================
# START
# =========================
bot = Bot()


async def send_message(text):
    channel = bot.get_channel(CHANNEL)
    if channel:
        await channel.send(text)


def run_bot():
    bot.run()


threading.Thread(target=run_bot, daemon=True).start()
threading.Thread(target=auto_loop, daemon=True).start()
threading.Thread(target=stream_watcher, daemon=True).start()

app.run(port=5000)
import os
import logging
import asyncio
from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Клиент Groq ---
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

# --- Память и Промпт ---
user_histories = {}

SYSTEM_PROMPT = """Ты — бот-тренажёр по русскому языку для 4 класса.
Твоя задача строго следовать алгоритму:
1. Напиши ОДНО короткое задание (например: вставь пропущенную букву, раскрой скобки, найди ошибку). Никаких объяснений правил!
2. Дождись ответа пользователя.
3. Проверь ответ. Если верно — похвали ("Верно!", "Молодец!"). Если неверно — дай правильный ответ (без длинных объяснений).
4. Сразу же напиши СЛЕДУЮЩЕЕ задание.

ПРАВИЛА:
- Не пиши длинные тексты. Максимум 2-3 предложения за раз.
- Никаких лекций и правил. Только задание и проверка.
- Задания должны быть простыми, для уровня 4 класса."""

def get_ai_reply(history):
    resp = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        max_tokens=300,
        temperature=0.7,
    )
    return resp.choices[0].message.content

# --- Логика Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user_histories[uid].append({"role": "user", "content": "Дай первое задание."})
    
    reply = await asyncio.to_thread(get_ai_reply, user_histories[uid])
    user_histories[uid].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_histories:
        await update.message.reply_text("Напиши /start чтобы начать тренировку.")
        return
    
    history = user_histories[uid]
    history.append({"role": "user", "content": update.message.text})
    
    if len(history) > 12:
        user_histories[uid] = [history[0]] + history[-11:]
        history = user_histories[uid]
        
    reply = await asyncio.to_thread(get_ai_reply, history)
    history.append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

# --- Инициализация Telegram ---
telegram_app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).updater(None).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

# --- Flask App ---
flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return "OK", 200

@flask_app.route("/webhook", methods=["POST"])
async def webhook():
    if request.method == "POST":
        update = Update.de_json(data=request.get_json(force=True), bot=telegram_app.bot)
        await telegram_app.update_queue.put(update)
        return Response(status=200)

# --- Инициализация при старте (для Gunicorn) ---
def init_bot():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://teach-bot-gljw.onrender.com")
    webhook_url = f"{render_url}/webhook"
    
    async def setup():
        await telegram_app.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook установлен: {webhook_url}")
        await telegram_app.initialize()
        await telegram_app.start()
    
    # Запускаем асинхронную настройку
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())

# Вызываем инициализацию при старте файла
init_bot()

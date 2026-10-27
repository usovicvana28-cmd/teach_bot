import os
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# --- Flask для Render ---
web = Flask(__name__)

@web.route("/")
def home():
    return "Bot is running"

@web.route("/health")
def health():
    return "OK"

# --- Groq клиент (совместим с OpenAI SDK) ---
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

# Память: user_id -> история диалога (последние 15 сообщений)
user_histories = {}

SYSTEM_PROMPT = """Ты — учитель русского языка для 4 класса. Веди урок по шагам:
1. Объясни одно простое правило (например, падеж, безударная гласная).
2. Приведи 1-2 примера.
3. Задай одно задание.
4. Дождись ответа ученика, оцени его и только потом переходи к следующему правилу.
Говори простым языком. Не задавай два задания подряд. Если ученик ошибается, объясни ошибку и дай похожее задание ещё раз."""

def get_ai_reply(history):
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",  # 14,400 запросов/день
        messages=history,
        max_tokens=400,
        temperature=0.7,
    )
    return resp.choices[0].message.content

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user_histories[uid].append({"role": "user", "content": "Начнём урок."})
    reply = get_ai_reply(user_histories[uid])
    user_histories[uid].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_histories:
        await update.message.reply_text("Напиши /start чтобы начать урок.")
        return

    history = user_histories[uid]
    history.append({"role": "user", "content": update.message.text})

    # Обрезаем историю до последних 15 сообщений (кроме system)
    if len(history) > 16:
        user_histories[uid] = [history[0]] + history[-15:]
        history = user_histories[uid]

    reply = get_ai_reply(history)
    history.append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

def run_bot():
    token = os.environ["TELEGRAM_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    web.run(host="0.0.0.0", port=port)
import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

# --- Заглушка для Render ---
web_app = Flask(__name__)

@web_app.route("/")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ---------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

user_histories = {}

# Короткий и четкий промпт
SYSTEM_PROMPT = """Ты — репетитор по русскому языку. Твоя цель — подготовить ученика к ЦТ.
Правила общения:
1. Не здоровайся каждый раз, не пиши длинные лекции. Просто дай задание.
2. Формат задания: вопрос и 4 варианта ответа (А, Б, В, Г).
3. Используй формат реальных тестов ЦТ (правописание, пунктуация, Н/НН).
4. Когда ученик отвечает, проверь его. Если верно — коротко похвали и задай НОВЫЙ вопрос. Если неверно — объясни ошибку и задай ПОХОЖИЙ вопрос.
5. НИКОГДА не придумывай сложные или двусмысленные вопросы. Если сомневаешься в правилах — задай простой вопрос на очевидное правило."""

async def get_ai_reply(history):
    try:
        # Используем встроенный поиск Groq, чтобы ИИ брал реальные задания ЦТ
        response = await client.chat.completions.create(
            model="qwen/qwen3.8-27b", 
            messages=history,
            max_tokens=400,
            temperature=0.5, # Снизили температуру (меньше креатива, больше точности)
            extra_body={
                "tools": [
                    {
                        "type": "browser_search"
                    }
                ]
            }
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка Groq: {e}")
        return "Ой, я задумался. Давай попробуем еще раз? Напиши любое сообщение."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Начинаем без лишних слов, сразу просим задание
    user_histories[uid].append({"role": "user", "content": "Дай мне первое задание в формате ЦТ."})
    
    await update.message.reply_text("⏳ Ищу задания в интернете...")
    reply = await get_ai_reply(user_histories[uid])
    user_histories[uid].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_histories:
        await update.message.reply_text("Привет! Напиши /start, чтобы начать подготовку к ЦТ.")
        return

    history = user_histories[uid]
    history.append({"role": "user", "content": update.message.text})

    if len(history) > 10: # Память сокращена до 10 сообщений, чтобы модель не путалась
        user_histories[uid] = [history[0]] + history[-9:]
        history = user_histories[uid]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await get_ai_reply(history)
    history.append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот ЦТ запущен...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

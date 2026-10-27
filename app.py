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

# Мягкий и дружелюбный промпт
SYSTEM_PROMPT = """Ты — добрый и поддерживающий репетитор по русскому языку. Твоя цель — мягко подготовить ученика к ЦТ.
Правила общения:
1. Будь вежливым и дружелюбным. Подбадривай ученика, если у него что-то не получается.
2. Не пиши длинные лекции. Дай одно задание и жди ответа.
3. Формат задания: вопрос и 4 варианта ответа (А, Б, В, Г). Используй темы ЦТ (правописание, пунктуация, Н/НН).
4. Когда ученик отвечает:
   - Если верно — искренне похвали и задай новый вопрос.
   - Если неверно — мягко объясни ошибку (например: "Почти получилось! Давай вспомним правило..."), поддержи ученика и предложи похожее, чуть более простое задание.
5. Не ругай ученика. Твоя задача — помочь ему поверить в свои силы."""

async def get_ai_reply(history):
    try:
        # Чистый запрос к Qwen без лишних инструментов
        response = await client.chat.completions.create(
            model="qwen/qwen3.8-27b", 
            messages=history,
            max_tokens=500,
            temperature=0.6
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка Groq: {e}")
        return "Ой, я задумался. Давай попробуем еще раз? Напиши любое сообщение."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user_histories[uid].append({"role": "user", "content": "Привет! Я готов начать урок. Дай мне первое задание."})
    
    await update.message.reply_text("⏳ Секунду, готовлю для тебя задание...")
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

    # Ограничиваем память 10 сообщениями (чтобы не перегружать модель)
    if len(history) > 10: 
        user_histories[uid] = [history[0]] + history[-9:]
        history = user_histories[uid]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await get_ai_reply(history)
    history.append({"role": "assistant", "content": reply})
    
    await update.message.reply_text(reply)

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("Токен TELEGRAM_TOKEN не найден!")
        return

    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот ЦТ запущен...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Клиент Groq (совместим с OpenAI)
client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

# Память для диалогов
user_histories = {}

SYSTEM_PROMPT = """Ты — добрый и нетерпеливый учитель русского языка для 11 класса. 
Твоя задача — вести мини-урок. Не пиши слишком длинные тексты.
Структура урока:
1. задай вопрос касательно правил русского языка
2. Дождись ответа ученика, проверь его и только потом переходи к следующему вопросу.
Говори простым языком. Если ученик ошибается, мягко объясни ошибку и дай похожее задание ещё раз."""

async def get_ai_reply(history):
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-20b", # Актуальная бесплатная модель Groq
            messages=history,
            max_tokens=400,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка Groq: {e}")
        return "Ой, я задумался и потерял мысль. Давай попробуем еще раз? Напиши 'Давай'."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logger.info(f"Пользователь {uid} начал урок.")
    
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user_histories[uid].append({"role": "user", "content": "Привет! Начнём урок."})
    
    await update.message.reply_text("⏳ Секунду, готовлю для тебя урок...")
    reply = await get_ai_reply(user_histories[uid])
    user_histories[uid].append({"role": "assistant", "content": reply})
    
    await update.message.reply_text(reply)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_histories:
        await update.message.reply_text("Привет! Напиши /start, чтобы начать наш урок.")
        return

    history = user_histories[uid]
    history.append({"role": "user", "content": update.message.text})

    # Обрезаем память, чтобы не превысить лимиты
    if len(history) > 16:
        user_histories[uid] = [history[0]] + history[-15:]
        history = user_histories[uid]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await get_ai_reply(history)
    history.append({"role": "assistant", "content": reply})
    
    await update.message.reply_text(reply)

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("Токен не найден!")
        return

    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен и слушает сообщения...")
    app.run_polling(drop_pending_updates=True) # drop_pending_updates сбрасывает старые сообщения

if __name__ == "__main__":
    main()

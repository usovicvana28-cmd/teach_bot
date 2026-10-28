import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI
import google.generativeai as genai

# --- Заглушка для Render ---
web_app = Flask(__name__)

@web_app.route("/")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ---------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Клиент Groq (Основной)
client_groq = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

# 2. Клиент Gemini (Резервный) - ОБНОВЛЕНО НА 2.5 FLASH LITE
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model_gemini = genai.GenerativeModel('gemini-2.5-flash-lite')

user_data = {}

SYSTEM_PROMPT = """Ты — добрый и поддерживающий репетитор. Твоя цель — узнать уровень ученика.
Правила общения:
1. Будь вежливым и строгим, если надо. Подбадривай ученика, если у него что-то не получается.
2. Не пиши длинные лекции. Дай одно задание и коментарий и жди ответа.
3. Формат задания: вопрос и 4 варианта ответа. 
4. Когда ученик отвечает:
   - Если верно — искренне похвали и задай новый вопрос.
   - Если неверно — поругай и объясни ошибку."""

# --- МАГИЯ ТУТ: Автоматический фолбэк (Groq -> Gemini) ---
async def get_ai_reply(history):
    try:
        response = await client_groq.chat.completions.create(
            model="qwen/qwen3.8-27b", 
            messages=history,
            max_tokens=500,
            temperature=0.6,
            extra_body={"reasoning_effort": "none"}
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.warning(f"Groq упал или исчерпал лимит: {e}. Переключаюсь на Gemini 2.5 Flash Lite...")
        
        try:
            # Переводим историю сообщений в простой текст для Gemini
            prompt_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
            
            response = await model_gemini.generate_content_async(prompt_text)
            return response.text
        except Exception as e2:
            logger.error(f"Обе модели недоступны: {e2}")
            return "⚠️ Все бесплатные модели на сегодня исчерпаны. Завтра снова будут доступны 2."
# -----------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data[uid] = {"mode": "learn", "history": [{"role": "system", "content": SYSTEM_PROMPT}]}
    user_data[uid]["history"].append({"role": "user", "content": "Привет! Я готов начать урок. Дай мне первое задание."})
    
    await update.message.reply_text("⏳ Секунду, готовлю для тебя задание...")
    reply = await get_ai_reply(user_data[uid]["history"])
    user_data[uid]["history"].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

async def exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data[uid] = {"mode": "exam_choose_subject"}
    await update.message.reply_text("📚 По какому предмету хочешь сдать экзамен? Напиши название (например: Математика, История, Русский язык).")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if uid not in user_data:
        await update.message.reply_text("Привет! Напиши /start, чтобы начать обучение, или /exam, чтобы сдать экзамен.")
        return

    if user_data[uid]["mode"] == "exam_choose_subject":
        user_data[uid]["mode"] = "exam_running"
        user_data[uid]["exam_subject"] = text
        user_data[uid]["current_q"] = 1
        user_data[uid]["score"] = 0
        
        prompt = [{"role": "system", "content": f"Ты — экзаменатор по предмету '{text}'. Задай ОДИН вопрос с 4 вариантами ответа (А, Б, В, Г). Без приветствий и лишнего текста. Только вопрос и варианты."}]
        prompt.append({"role": "user", "content": "Дай первый вопрос."})
        
        await update.message.reply_text(f"📝 Вопрос 1 из 10:")
        reply = await get_ai_reply(prompt)
        await update.message.reply_text(reply)
        return

    if user_data[uid]["mode"] == "exam_running":
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        subject = user_data[uid]["exam_subject"]
        check_prompt = [
            {"role": "system", "content": f"Ты — экзаменатор по '{subject}'. Тебе дали ответ ученика. Скажи только 'ДА' (без кавычек), если ответ правильный, или 'НЕТ' (без кавычек), если неправильный."},
            {"role": "user", "content": f"Ученик ответил: {text}. Это правильно?"}
        ]
        
        check_reply = await get_ai_reply(check_prompt)
        
        if "ДА" in check_reply.upper():
            user_data[uid]["score"] += 1

        user_data[uid]["current_q"] += 1

        if user_data[uid]["current_q"] <= 10:
            prompt = [{"role": "system", "content": f"Ты — экзаменатор по предмету '{subject}'. Задай ОДИН вопрос с 4 вариантами ответа (А, Б, В, Г). Без приветствий и лишнего текста. Только вопрос и варианты."}]
            prompt.append({"role": "user", "content": f"Дай следующий вопрос, это вопрос номер {user_data[uid]['current_q']} из 10."})
            
            await update.message.reply_text(f"📝 Вопрос {user_data[uid]['current_q']} из 10:")
            reply = await get_ai_reply(prompt)
            await update.message.reply_text(reply)
        else:
            score = user_data[uid]["score"]
            await update.message.reply_text(f"🏁 Экзамен по предмету '{subject}' завершен!\nТвой результат: {score} из 10.")
            user_data[uid] = {"mode": "learn", "history": [{"role": "system", "content": SYSTEM_PROMPT}]}
            await update.message.reply_text("Напиши /start, чтобы вернуться к обычным урокам, или /exam, чтобы сдать еще один экзамен.")
        return

    if user_data[uid]["mode"] == "learn":
        history = user_data[uid]["history"]
        history.append({"role": "user", "content": text})

        if len(history) > 10: 
            user_data[uid]["history"] = [history[0]] + history[-9:]
            history = user_data[uid]["history"]

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
    app.add_handler(CommandHandler("exam", exam))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

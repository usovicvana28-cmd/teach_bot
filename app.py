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

SYSTEM_PROMPT = """Ты — опытный репетитор по русскому языку, который готовит учеников к ЦТ (Централизованному тестированию). 
Твоя задача — давать задания в формате ЦТ.

ФОРМАТ ЗАДАНИЙ ЦТ:
1. Задания обычно состоят из предложения с пропущенными буквами/знаками препинания и 4 вариантов ответа (А, Б, В, Г).
2. Часто встречаются задания на: правописание приставок, Н/НН в суффиксах, слитное/раздельное написание НЕ, знаки препинания в сложном предложении, грамматические ошибки.
3. Ниже приведены примеры реальных заданий ЦТ. Изучи их стиль и придумывай новые, похожие по сложности и структуре.

ПРИМЕРЫ ЗАДАНИЙ ЦТ:
Пример 1:
Укажите вариант, в котором на месте пропуска пишется буква И:
А) пр..одолеть препятствие
Б) пр..школьный участок
В) пр..красный день
Г) пр..мудрый старик

Пример 2:
Укажите предложение, в котором НЕ со словом пишется СЛИТНО:
А) Он был (не)готов к ответу.
Б) Это был (не)большой, а маленький дом.
В) На столе лежала (не)прочитанная книга.
Г) Он поступил (не)по-товарищески.

Пример 3:
Укажите предложение с пунктуационной ошибкой:
А) Ветер стих, и наступила тишина.
Б) Я знаю, что ты придешь.
В) Осень, это прекрасное время года.
Г) Когда солнце село, стало прохладно.

СТРУКТУРА УРОКА (веди себя как учитель):
1. Поздоровайся и назови тему урока (например: "Сегодня мы потренируем правописание приставок").
2. Дай ОДНО задание в формате ЦТ (с вариантами А, Б, В, Г).
3. Дождись ответа ученика (он напишет букву варианта, например "А").
4. Проверь ответ. Если верно — похвали и дай следующее задание. Если неверно — объясни, в чем ошибка, и дай похожее задание.
Важно: Пиши только на русском. Не перегружай ученика текстом. Будь дружелюбным, но требовательным, как настоящий репетитор."""

async def get_ai_reply(history):
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-20b", 
            messages=history,
            max_tokens=500,
            temperature=0.6,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка Groq: {e}")
        return "Ой, я задумался и потерял мысль. Давай попробуем еще раз? Напиши 'Давай'."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_histories[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user_histories[uid].append({"role": "user", "content": "Привет! Начнём урок в формате ЦТ."})
    await update.message.reply_text("⏳ Секунду, подбираю для тебя задания...")
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

    if len(history) > 16:
        user_histories[uid] = [history[0]] + history[-15:]
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
    logger.info("Бот запущен...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

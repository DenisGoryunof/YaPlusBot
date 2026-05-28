import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import uvicorn

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
CRON_SECRET = os.getenv("CRON_SECRET")
DATA_FILE = "data.json"
MONTH_PRICE = 100

# ==================== ВСЕ ВАШИ ФУНКЦИИ: load_data, update_user, клавиатуры, хэндлеры (start, new_chat_member и т.д.) ====================
# ... (ВСТАВЬТЕ СЮДА ВЕСЬ ВАШ СУЩЕСТВУЮЩИЙ КОД, КОТОРЫЙ ИДЕТ ОТ load_data ДО admin_command) ...
# --- (Ваш код с хэндлерами: start, new_chat_member_handler, my_subscription_callback, ... admin_command) ---

# --- Функция отправки напоминаний ---
async def send_reminders():
    # ... (оставьте эту функцию без изменений) ...
    pass

# --- FastAPI приложение (оставляем без изменений) ---
app = FastAPI()

@app.get("/cron")
async def cron(request: Request):
    # ... (оставьте эту функцию без изменений) ...
    pass

@app.get("/")
async def index():
    return {"message": "Bot is running"}

# ==================== ИСПРАВЛЕННАЯ ЧАСТЬ ДЛЯ ЗАПУСКА ====================
def run_bot():
    """Запускает бота в режиме Long Polling в отдельном потоке."""
    # 1. Создаем и устанавливаем НОВЫЙ event loop для этого потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 2. Создаем и настраиваем приложение бота
    bot_app = Application.builder().token(BOT_TOKEN).build()

    # --- Регистрация всех хэндлеров ---
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("admin", admin_command))
    bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    bot_app.add_handler(CallbackQueryHandler(my_subscription_callback, pattern="^my_subscription$"))
    bot_app.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay$"))
    bot_app.add_handler(CallbackQueryHandler(amount_callback, pattern="^amount_|^back_to_main$"))
    bot_app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_|^back_to_main$"))
    bot_app.add_handler(CallbackQueryHandler(confirm_callback, pattern="^confirm_|^reject_$"))
    bot_app.add_handler(CallbackQueryHandler(manual_select_callback, pattern="^manual_select_"))
    bot_app.add_handler(CallbackQueryHandler(manual_extend_callback, pattern="^manual_months_"))
    bot_app.add_handler(CallbackQueryHandler(back_to_admin_panel_callback, pattern="^back_to_admin_panel$"))

    # 3. Ключевой момент: сбрасываем вебхук ПЕРЕД запуском поллинга
    async def clear_and_poll():
        # Удаляем вебхук, игнорируя все ожидающие обновления
        await bot_app.bot.delete_webhook(drop_pending_updates=True)
        print("Old webhook cleared. Starting polling...")
        # Запускаем long polling
        await bot_app.run_polling()

    print("Initializing bot in background thread...")
    # Запускаем нашу асинхронную функцию в созданном event loop
    loop.run_until_complete(clear_and_poll())
    loop.close()

# --- Точка входа ---
if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем FastAPI сервер
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

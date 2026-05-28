import os
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import threading
import uvicorn

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
CRON_SECRET = os.getenv("CRON_SECRET")
DATA_FILE = "data.json"
MONTH_PRICE = 100

# --- Работа с JSON ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "settings": {"price_per_month": MONTH_PRICE}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(user_id):
    data = load_data()
    return data["users"].get(str(user_id))

def update_user(user_id, **kwargs):
    data = load_data()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {"subscription_end": "1970-01-01", "username": None, "first_name": None}
    for key, value in kwargs.items():
        if value is not None:
            data["users"][uid][key] = value
    save_data(data)

def set_subscription_end(user_id, end_date):
    update_user(user_id, subscription_end=end_date.strftime("%Y-%m-%d"))

def get_subscription_end(user_id):
    user = get_user(user_id)
    if user:
        end_str = user.get("subscription_end")
        if end_str and end_str != "1970-01-01":
            return datetime.strptime(end_str, "%Y-%m-%d").date()
    return None

# --- Клавиатуры ---
def main_menu_keyboard():
    keyboard = [[InlineKeyboardButton("💰 Оплатить", callback_data="pay")], [InlineKeyboardButton("📅 Моя подписка", callback_data="my_subscription")]]
    return InlineKeyboardMarkup(keyboard)

def payment_amount_keyboard():
    keyboard = [
        [InlineKeyboardButton("100 руб", callback_data="amount_100"), InlineKeyboardButton("200 руб", callback_data="amount_200")],
        [InlineKeyboardButton("300 руб", callback_data="amount_300"), InlineKeyboardButton("500 руб", callback_data="amount_500")],
        [InlineKeyboardButton("🔢 Другая сумма", callback_data="amount_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_confirm_keyboard(user_id, amount):
    keyboard = [[InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{user_id}_{amount}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}_{amount}")]]
    return InlineKeyboardMarkup(keyboard)

def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Установить цену", callback_data="admin_set_price")],
        [InlineKeyboardButton("📋 Список подписчиков", callback_data="admin_list_users")],
        [InlineKeyboardButton("🔧 Продлить вручную", callback_data="admin_manual_extend")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Хэндлеры ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        update_user(update.effective_user.id, username=update.effective_user.username, first_name=update.effective_user.first_name)
        await update.message.reply_text("Добро пожаловать! Используйте меню ниже.", reply_markup=main_menu_keyboard())

async def new_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == GROUP_ID:
        for member in update.message.new_chat_members:
            if member.id != context.bot.id:
                update_user(member.id, username=member.username, first_name=member.first_name)
                await context.bot.send_message(member.id, "Вы были добавлены в группу подписчиков. Настройте подписку, нажав /start в личке со мной.")

async def my_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    end_date = get_subscription_end(query.from_user.id)
    text = f"📅 Ваша подписка активна до {end_date.strftime('%d.%m.%Y')}." if end_date and end_date >= datetime.now().date() else "❗ У вас нет активной подписки. Нажмите «Оплатить», чтобы продлить."
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())

async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите сумму оплаты:", reply_markup=payment_amount_keyboard())

async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("amount_"):
        amount_str = data.split("_")[1]
        if amount_str == "custom":
            await query.edit_message_text("Введите сумму в рублях (целое число):")
            context.user_data["waiting_for_custom"] = True
        else:
            amount = int(amount_str)
            user = get_user(query.from_user.id)
            username = user.get("username", "Unknown")
            await context.bot.send_message(ADMIN_ID, f"🔔 Пользователь @{username} (ID: {query.from_user.id}) запросил оплату на сумму {amount} руб.\nПодтвердить продление?", reply_markup=admin_confirm_keyboard(query.from_user.id, amount))
            await query.edit_message_text(f"Запрос на оплату {amount} руб. отправлен администратору. Ожидайте подтверждения.")
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("У вас нет прав.", show_alert=True)
        return
    data = query.data
    if data.startswith("confirm_"):
        _, user_id_str, amount_str = data.split("_")
        user_id, amount = int(user_id_str), int(amount_str)
        price_per_month = load_data()["settings"]["price_per_month"]
        months = max(1, amount // price_per_month)
        current_end = get_subscription_end(user_id)
        if current_end and current_end >= datetime.now().date():
            new_end = datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)
        else:
            new_end = datetime.now().date() + timedelta(days=30 * months)
        set_subscription_end(user_id, new_end)
        await context.bot.send_message(user_id, f"✅ Ваша подписка продлена до {new_end.strftime('%d.%m.%Y')}.")
        await context.bot.send_message(ADMIN_ID, f"✅ Подписка пользователя {user_id} продлена на {months} мес.")
        await query.edit_message_text(f"✅ Подтверждена оплата {amount} руб. для пользователя {user_id}. Подписка продлена.")
    elif data.startswith("reject_"):
        _, user_id_str, amount_str = data.split("_")
        user_id, amount = int(user_id_str), int(amount_str)
        await context.bot.send_message(user_id, f"❌ Ваш запрос на оплату {amount} руб. отклонён.")
        await query.edit_message_text(f"❌ Запрос пользователя {user_id} отклонён.")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("У вас нет прав.", show_alert=True)
        return
    data = query.data
    if data == "admin_set_price":
        await query.edit_message_text("Введите новую цену за месяц (в рублях):")
        context.user_data["waiting_for_price"] = True
    elif data == "admin_list_users":
        users = load_data()["users"]
        if not users:
            text = "Список подписчиков пуст."
        else:
            lines = []
            for uid, info in users.items():
                end = info.get("subscription_end", "неактивна")
                if end != "1970-01-01":
                    end = datetime.strptime(end, "%Y-%m-%d").strftime("%d.%m.%Y")
                else:
                    end = "неактивна"
                username = info.get("username", uid)
                lines.append(f"@{username}: {end}")
            text = "Подписчики:\n" + "\n".join(lines)
        await query.edit_message_text(text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        users = load_data()["users"]
        if not users:
            await query.edit_message_text("Нет зарегистрированных пользователей.")
            return
        keyboard = []
        for uid, info in users.items():
            if uid == str(ADMIN_ID):
                continue
            username = info.get("username") or info.get("first_name") or uid
            keyboard.append([InlineKeyboardButton(username, callback_data=f"manual_select_{uid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
        await query.edit_message_text("Выберите пользователя для продления:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def manual_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.data.split("_")[2]
    context.user_data["manual_user_id"] = user_id
    keyboard = [
        [InlineKeyboardButton("1 месяц", callback_data="manual_months_1")],
        [InlineKeyboardButton("3 месяца", callback_data="manual_months_3")],
        [InlineKeyboardButton("6 месяцев", callback_data="manual_months_6")],
        [InlineKeyboardButton("12 месяцев", callback_data="manual_months_12")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")]
    ]
    await query.edit_message_text("Выберите количество месяцев:", reply_markup=InlineKeyboardMarkup(keyboard))

async def manual_extend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    months = int(query.data.split("_")[2])
    user_id = int(context.user_data.get("manual_user_id"))
    if not user_id:
        await query.edit_message_text("Ошибка: пользователь не выбран.")
        return
    current_end = get_subscription_end(user_id)
    if current_end and current_end >= datetime.now().date():
        new_end = datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    await query.edit_message_text(f"✅ Подписка пользователя {user_id} продлена до {new_end.strftime('%d.%m.%Y')}.")
    await context.bot.send_message(user_id, f"Администратор продлил вашу подписку до {new_end.strftime('%d.%m.%Y')}.")
    context.user_data.clear()
    await query.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

async def back_to_admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Панель администратора:", reply_markup=admin_panel_keyboard())
    context.user_data.clear()

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if update.message and update.message.new_chat_members:
        for member in update.message.new_chat_members:
            if member.id != context.bot.id:
                update_user(member.id, username=member.username, first_name=member.first_name)
                await context.bot.send_message(member.id, "Вы были добавлены в группу подписчиков. Настройте подписку, нажав /start в личке со мной.")
        return

    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            if amount <= 0:
                raise ValueError
            user = get_user(user_id)
            username = user.get("username", "Unknown")
            await context.bot.send_message(ADMIN_ID, f"🔔 Пользователь @{username} (ID: {user_id}) запросил оплату на сумму {amount} руб.\nПодтвердить продление?", reply_markup=admin_confirm_keyboard(user_id, amount))
            await update.message.reply_text(f"Запрос на оплату {amount} руб. отправлен администратору. Ожидайте подтверждения.")
        except:
            await update.message.reply_text("Пожалуйста, введите целое положительное число.")
        context.user_data["waiting_for_custom"] = False
        return

    if user_id == ADMIN_ID and context.user_data.get("waiting_for_price"):
        try:
            new_price = int(text)
            if new_price <= 0:
                raise ValueError
            data = load_data()
            data["settings"]["price_per_month"] = new_price
            save_data(data)
            await update.message.reply_text(f"✅ Цена за месяц установлена: {new_price} руб.")
        except:
            await update.message.reply_text("Ошибка: введите целое положительное число.")
        context.user_data["waiting_for_price"] = False
        return

    if update.effective_chat.type == "private":
        await update.message.reply_text("Используйте меню ниже.", reply_markup=main_menu_keyboard())

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав.")
        return
    await update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

# --- Функция отправки напоминаний ---
async def send_reminders():
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    data = load_data()
    users = data["users"]
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    for uid_str, info in users.items():
        uid = int(uid_str)
        if uid == ADMIN_ID:
            continue
        end_str = info.get("subscription_end")
        if not end_str or end_str == "1970-01-01":
            text = "❗ У вас нет активной подписки. Пожалуйста, оплатите, нажав /pay в группе."
            await bot.send_message(uid, text)
            continue
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        if end_date <= tomorrow:
            if end_date < today:
                text = f"⚠️ Ваша подписка истекла {end_date.strftime('%d.%m.%Y')}. Пожалуйста, оплатите, нажав /pay в группе."
            else:
                text = f"⚠️ Ваша подписка истекает {end_date.strftime('%d.%m.%Y')}. Для продления нажмите /pay в группе."
            await bot.send_message(uid, text)

# --- FastAPI приложение (только для страниц и /cron) ---
app = FastAPI()

@app.get("/cron")
async def cron(request: Request):
    secret = request.query_params.get("secret")
    if secret != CRON_SECRET:
        return {"error": "Forbidden"}, 403
    try:
        await send_reminders()
        return {"status": "OK"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/")
async def index():
    return {"message": "Bot is running"}

# --- Инициализация и запуск бота в режиме Long Polling ---
def run_bot():
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    import asyncio
    asyncio.run(bot_app.bot.delete_webhook(drop_pending_updates=True))
    print("Old webhook deleted")
    
    # Регистрируем хэндлеры
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
    
    print("Starting bot in long polling mode...")
    bot_app.run_polling()

# Запускаем всё вместе
if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Запускаем FastAPI сервер
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

import os
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- Загрузка переменных окружения ---xn
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
CRON_SECRET = os.getenv("CRON_SECRET")
DATA_FILE = "data.json"
MONTH_PRICE = 100

# --- Работа с JSON (Без изменений) ---
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

# --- Клавиатуры (Без изменений) ---
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

# --- Хэндлеры (Все переписаны в async def) ---
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
        new_end = (datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)) if current_end and current_end >= datetime.now().date() else datetime.now().date() + timedelta(days=30 * months)
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
        text = "Список подписчиков пуст." if not users else "\n".join([f"@{info.get('username', uid)}: {info.get('subscription_end', 'неактивна') if info.get('subscription_end') != '1970-01-01' else 'неактивна'}" for uid, info in users.items()])
        await query.edit_message_text(text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        users = load_data()["users"]
        if not users:
            await query.edit_message_text("Нет зарегистрированных пользователей.")
            return
        keyboard = [[InlineKeyboardButton(info.get('username') or info.get('first_name') or uid, callback_data=f"manual_select_{uid}")] for uid, info in users.items() if uid != str(ADMIN_ID)]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
        await query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def manual_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.data.split("_")[2]
    context.user_data["manual_user_id"] = user_id
    keyboard = [[InlineKeyboardButton(f"{m} месяц(ев)", callback_data=f"manual_months_{m}")] for m in [1, 3, 6, 12]]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
    await query.edit_message_text("Выберите количество месяцев:", reply_markup=InlineKeyboardMarkup(keyboard))

async def manual_extend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    months = int(query.data.split("_")[2])
    user_id = int(context.user_data.get("manual_user_id"))
    if not user_id:
        await query.edit_message_text("Ошибка.")
        return
    current_end = get_subscription_end(user_id)
    new_end = (datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)) if current_end and current_end >= datetime.now().date() else datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    await context.bot.send_message(user_id, f"Администратор продлил вашу подписку до {new_end.strftime('%d.%m.%Y')}.")
    await query.edit_message_text(f"✅ Подписка пользователя {user_id} продлена до {new_end.strftime('%d.%m.%Y')}.")
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
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            if amount <= 0: raise ValueError
            user = get_user(user_id)
            username = user.get("username", "Unknown")
            await context.bot.send_message(ADMIN_ID, f"🔔 Пользователь @{username} (ID: {user_id}) запросил оплату на сумму {amount} руб.\nПодтвердить продление?", reply_markup=admin_confirm_keyboard(user_id, amount))
            await update.message.reply_text(f"Запрос на оплату {amount} руб. отправлен администратору.")
        except:
            await update.message.reply_text("Введите целое положительное число.")
        context.user_data["waiting_for_custom"] = False
    elif user_id == ADMIN_ID and context.user_data.get("waiting_for_price"):
        try:
            new_price = int(text)
            if new_price <= 0: raise ValueError
            data = load_data()
            data["settings"]["price_per_month"] = new_price
            save_data(data)
            await update.message.reply_text(f"✅ Цена установлена: {new_price} руб.")
        except:
            await update.message.reply_text("Ошибка.")
        context.user_data["waiting_for_price"] = False
    elif update.effective_chat.type == "private":
        await update.message.reply_text("Используйте меню.", reply_markup=main_menu_keyboard())

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("У вас нет прав.")
        return
    await update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

async def send_reminders():
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    data = load_data()
    today, tomorrow = datetime.now().date(), datetime.now().date() + timedelta(days=1)
    for uid_str, info in data["users"].items():
        uid = int(uid_str)
        if uid == ADMIN_ID: continue
        end_str = info.get("subscription_end")
        if not end_str or end_str == "1970-01-01":
            await bot.send_message(uid, "❗ У вас нет активной подписки. Пожалуйста, оплатите, нажав /pay в группе.")
            continue
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        if end_date <= tomorrow:
            await bot.send_message(uid, f"⚠️ Ваша подписка {'истекла' if end_date < today else 'истекает'} {end_date.strftime('%d.%m.%Y')}. Для продления нажмите /pay в группе.")

# --- FastAPI приложение ---
app = FastAPI()
bot_app = Application.builder().token(BOT_TOKEN).build()
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

@app.post(f"/{BOT_TOKEN}")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.process_update(update)
    return {"status": "ok"}

@app.get("/cron")
async def cron(request: Request):
    if request.query_params.get("secret") != CRON_SECRET:
        return {"error": "Forbidden"}, 403
    try:
        await send_reminders()
        return {"status": "OK"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/")
async def index():
    return {"message": "Bot is running"}

# --- Запуск бота в режиме Long Polling ---
if __name__ == "__main__":
    import asyncio
    import uvicorn
    from threading import Thread

    # Запускаем Flask-сервер в отдельном потоке (чтобы он отвечал на /cron)
    def run_flask():
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Запускаем бота в режиме Long Polling (в главном потоке)
    print("Starting bot in long polling mode...")
    bot_app.run_polling()

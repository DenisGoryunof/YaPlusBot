import os
import json
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
CRON_SECRET = os.getenv("CRON_SECRET")
DATA_FILE = "data.json"
MONTH_PRICE = 100

# ========== РАБОТА С JSON ==========
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "settings": {"price_per_month": MONTH_PRICE}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
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

# ========== КЛАВИАТУРЫ ==========
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

# ========== ХЭНДЛЕРЫ ==========
async def start(update, context):
    if update.effective_chat.type == "private":
        user = update.effective_user
        update_user(user.id, username=user.username, first_name=user.first_name)
        await update.message.reply_text("Добро пожаловать!", reply_markup=main_menu_keyboard())

async def my_subscription_callback(update, context):
    query = update.callback_query
    await query.answer()
    end_date = get_subscription_end(query.from_user.id)
    text = f"📅 Активна до {end_date.strftime('%d.%m.%Y')}." if end_date and end_date >= datetime.now().date() else "❗ Нет активной подписки."
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())

async def pay_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите сумму:", reply_markup=payment_amount_keyboard())

async def amount_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("amount_"):
        amount_str = data.split("_")[1]
        if amount_str == "custom":
            await query.edit_message_text("Введите сумму:")
            context.user_data["waiting_for_custom"] = True
        else:
            await query.edit_message_text(f"Запрос на {amount_str} руб. отправлен админу.")
            user = get_user(query.from_user.id)
            await context.bot.send_message(ADMIN_ID, f"🔔 @{user.get('username')} запросил {amount_str} руб.", reply_markup=admin_confirm_keyboard(query.from_user.id, int(amount_str)))
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def confirm_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет прав.")
        return
    data = query.data
    if data.startswith("confirm_"):
        _, user_id_str, amount_str = data.split("_")
        user_id, amount = int(user_id_str), int(amount_str)
        price = load_data()["settings"]["price_per_month"]
        months = max(1, amount // price)
        end_date = get_subscription_end(user_id)
        if end_date and end_date >= datetime.now().date():
            new_end = end_date + timedelta(days=30 * months)
        else:
            new_end = datetime.now().date() + timedelta(days=30 * months)
        set_subscription_end(user_id, new_end)
        await context.bot.send_message(user_id, f"✅ Продлена до {new_end.strftime('%d.%m.%Y')}.")
        await query.edit_message_text(f"✅ Подтверждено.")
    elif data.startswith("reject_"):
        _, user_id_str, amount_str = data.split("_")
        user_id, amount = int(user_id_str), int(amount_str)
        await context.bot.send_message(user_id, f"❌ Запрос отклонён.")
        await query.edit_message_text(f"❌ Отклонено.")

async def admin_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет прав.")
        return
    data = query.data
    if data == "admin_set_price":
        await query.edit_message_text("Введите новую цену:")
        context.user_data["waiting_for_price"] = True
    elif data == "admin_list_users":
        users = load_data()["users"]
        text = "Пусто" if not users else "\n".join([f"@{info.get('username', uid)}: {info.get('subscription_end', 'нет')}" for uid, info in users.items()])
        await query.edit_message_text(text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        users = load_data()["users"]
        if not users:
            await query.edit_message_text("Нет пользователей.")
            return
        keyboard = [[InlineKeyboardButton(info.get('username') or uid, callback_data=f"manual_select_{uid}")] for uid, info in users.items() if uid != str(ADMIN_ID)]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
        await query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def manual_select_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.data.split("_")[2]
    context.user_data["manual_user_id"] = user_id
    keyboard = [[InlineKeyboardButton(f"{m} мес", callback_data=f"manual_months_{m}")] for m in [1,3,6,12]]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
    await query.edit_message_text("Выберите срок:", reply_markup=InlineKeyboardMarkup(keyboard))

async def manual_extend_callback(update, context):
    query = update.callback_query
    await query.answer()
    months = int(query.data.split("_")[2])
    user_id = int(context.user_data.get("manual_user_id"))
    if not user_id:
        await query.edit_message_text("Ошибка.")
        return
    end_date = get_subscription_end(user_id)
    if end_date and end_date >= datetime.now().date():
        new_end = end_date + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    await query.edit_message_text(f"✅ Продлён до {new_end.strftime('%d.%m.%Y')}.")
    await context.bot.send_message(user_id, f"Админ продлил до {new_end.strftime('%d.%m.%Y')}.")

async def back_to_admin_panel_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Панель администратора:", reply_markup=admin_panel_keyboard())
    context.user_data.clear()

async def text_message_handler(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            await update.message.reply_text(f"Запрос на {amount} руб. отправлен.")
            await context.bot.send_message(ADMIN_ID, f"🔔 @{get_user(user_id).get('username')} запросил {amount} руб.", reply_markup=admin_confirm_keyboard(user_id, amount))
        except:
            await update.message.reply_text("Введите число.")
        context.user_data["waiting_for_custom"] = False
    elif user_id == ADMIN_ID and context.user_data.get("waiting_for_price"):
        try:
            new_price = int(text)
            data = load_data()
            data["settings"]["price_per_month"] = new_price
            save_data(data)
            await update.message.reply_text(f"✅ Цена {new_price} руб.")
        except:
            await update.message.reply_text("Ошибка.")
        context.user_data["waiting_for_price"] = False
    elif update.effective_chat.type == "private":
        await update.message.reply_text("Используйте меню.", reply_markup=main_menu_keyboard())

async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет прав.")
        return
    await update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

# ========== НАПОМИНАНИЯ ЧЕРЕЗ FLASK ==========
flask_app = Flask(__name__)

@flask_app.route("/cron")
def cron():
    secret = request.args.get("secret")
    if secret != CRON_SECRET:
        return "Forbidden", 403
    try:
        import asyncio
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        data = load_data()
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        for uid_str, info in data["users"].items():
            uid = int(uid_str)
            if uid == ADMIN_ID:
                continue
            end_str = info.get("subscription_end")
            if not end_str or end_str == "1970-01-01":
                asyncio.run(bot.send_message(uid, "❗ Нет активной подписки. Нажмите /pay."))
                continue
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            if end_date <= tomorrow:
                asyncio.run(bot.send_message(uid, f"⚠️ Подписка {'истекла' if end_date < today else 'истекает'} {end_date.strftime('%d.%m.%Y')}. Нажмите /pay."))
        return "OK"
    except Exception as e:
        return str(e), 500

@flask_app.route("/")
def index():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ========== ЗАПУСК БОТА ==========
def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    app.add_handler(CallbackQueryHandler(my_subscription_callback, pattern="^my_subscription$"))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay$"))
    app.add_handler(CallbackQueryHandler(amount_callback, pattern="^amount_|^back_to_main$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_|^back_to_main$"))
    app.add_handler(CallbackQueryHandler(confirm_callback, pattern="^confirm_|^reject_$"))
    app.add_handler(CallbackQueryHandler(manual_select_callback, pattern="^manual_select_"))
    app.add_handler(CallbackQueryHandler(manual_extend_callback, pattern="^manual_months_"))
    app.add_handler(CallbackQueryHandler(back_to_admin_panel_callback, pattern="^back_to_admin_panel$"))
    
    async def start_polling():
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared")
        await app.run_polling()
    
    import asyncio
    asyncio.run(start_polling())

if __name__ == "__main__":
    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()
    run_bot()

import os
import json
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

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
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    if update.effective_chat.type == "private":
        update_user(user.id, username=user.username, first_name=user.first_name)
        update.message.reply_text("Добро пожаловать! Используйте меню ниже.", reply_markup=main_menu_keyboard())

def my_subscription(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    end_date = get_subscription_end(query.from_user.id)
    text = f"📅 Ваша подписка активна до {end_date.strftime('%d.%m.%Y')}." if end_date and end_date >= datetime.now().date() else "❗ У вас нет активной подписки. Нажмите «Оплатить»."
    query.edit_message_text(text, reply_markup=main_menu_keyboard())

def pay(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("Выберите сумму оплаты:", reply_markup=payment_amount_keyboard())

def send_admin_notification(bot, user_id, amount):
    user = get_user(user_id)
    username = user.get("username", "Unknown")
    text = f"🔔 Пользователь @{username} (ID: {user_id}) запросил оплату {amount} руб.\nПодтвердить?"
    bot.send_message(ADMIN_ID, text, reply_markup=admin_confirm_keyboard(user_id, amount))

def extend_subscription(bot, user_id, amount):
    data = load_data()
    price_per_month = data["settings"]["price_per_month"]
    months = max(1, amount // price_per_month)
    current_end = get_subscription_end(user_id)
    if current_end and current_end >= datetime.now().date():
        new_end = current_end + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    bot.send_message(user_id, f"✅ Подписка продлена до {new_end.strftime('%d.%m.%Y')}.")
    bot.send_message(ADMIN_ID, f"✅ Подписка {user_id} продлена на {months} мес.")

def amount(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("amount_"):
        amount_str = data.split("_")[1]
        if amount_str == "custom":
            query.edit_message_text("Введите сумму (целое число):")
            context.user_data["waiting_for_custom"] = True
        else:
            amount = int(amount_str)
            send_admin_notification(context.bot, query.from_user.id, amount)
            query.edit_message_text(f"Запрос на {amount} руб. отправлен админу.")
    elif data == "back_to_main":
        query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

def confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.from_user.id != ADMIN_ID:
        query.answer("Нет прав.", show_alert=True)
        return
    data = query.data
    if data.startswith("confirm_"):
        _, uid, amt = data.split("_")
        extend_subscription(context.bot, int(uid), int(amt))
        query.edit_message_text(f"✅ Подтверждена оплата {amt} руб.")
    elif data.startswith("reject_"):
        _, uid, amt = data.split("_")
        context.bot.send_message(int(uid), f"❌ Запрос на {amt} руб. отклонён.")
        query.edit_message_text(f"❌ Запрос отклонён.")

def admin_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.from_user.id != ADMIN_ID:
        query.answer("Нет прав.", show_alert=True)
        return
    data = query.data
    if data == "admin_set_price":
        query.edit_message_text("Введите новую цену за месяц:")
        context.user_data["waiting_for_price"] = True
    elif data == "admin_list_users":
        users = load_data()["users"]
        text = "Пусто" if not users else "\n".join([f"@{info.get('username', uid)}: {info.get('subscription_end', 'нет')}" for uid, info in users.items()])
        query.edit_message_text(text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        users = load_data()["users"]
        if not users:
            query.edit_message_text("Нет пользователей.")
            return
        keyboard = []
        for uid, info in users.items():
            if uid == str(ADMIN_ID):
                continue
            name = info.get("username") or info.get("first_name") or uid
            keyboard.append([InlineKeyboardButton(name, callback_data=f"mselect_{uid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
        query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "back_to_main":
        query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

def manual_select(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    uid = query.data.split("_")[1]
    context.user_data["manual_uid"] = uid
    keyboard = [[InlineKeyboardButton(f"{m} мес", callback_data=f"mextend_{m}")] for m in [1,3,6,12]]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
    query.edit_message_text("Выберите срок:", reply_markup=InlineKeyboardMarkup(keyboard))

def manual_extend(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    months = int(query.data.split("_")[1])
    uid = int(context.user_data.get("manual_uid"))
    if not uid:
        query.edit_message_text("Ошибка.")
        return
    current_end = get_subscription_end(uid)
    if current_end and current_end >= datetime.now().date():
        new_end = current_end + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(uid, new_end)
    context.bot.send_message(uid, f"Админ продлил подписку до {new_end.strftime('%d.%m.%Y')}.")
    query.edit_message_text(f"✅ Продлён до {new_end.strftime('%d.%m.%Y')}.")

def text_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            if amount <= 0: raise ValueError
            send_admin_notification(context.bot, user_id, amount)
            update.message.reply_text(f"Запрос на {amount} руб. отправлен.")
        except:
            update.message.reply_text("Введите число > 0.")
        context.user_data["waiting_for_custom"] = False
    elif user_id == ADMIN_ID and context.user_data.get("waiting_for_price"):
        try:
            new_price = int(text)
            if new_price <= 0: raise ValueError
            data = load_data()
            data["settings"]["price_per_month"] = new_price
            save_data(data)
            update.message.reply_text(f"✅ Цена {new_price} руб.")
        except:
            update.message.reply_text("Ошибка.")
        context.user_data["waiting_for_price"] = False
    elif update.effective_chat.type == "private":
        update.message.reply_text("Используйте меню.", reply_markup=main_menu_keyboard())

def admin_command(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("Нет прав.")
        return
    update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

# ========== НАПОМИНАНИЯ ==========
def send_reminders():
    bot = telegram.Bot(token=BOT_TOKEN)
    data = load_data()
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    for uid_str, info in data["users"].items():
        uid = int(uid_str)
        if uid == ADMIN_ID: continue
        end_str = info.get("subscription_end")
        if not end_str or end_str == "1970-01-01":
            bot.send_message(uid, "❗ Нет активной подписки. Нажмите /pay.")
            continue
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        if end_date <= tomorrow:
            msg = f"⚠️ Подписка {'истекла' if end_date < today else 'истекает'} {end_date.strftime('%d.%m.%Y')}. Нажмите /pay."
            bot.send_message(uid, msg)

# ========== FLASK ==========
app = Flask(__name__)

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), None)
    updater.dispatcher.process_update(update)
    return "ok"

@app.route("/cron")
def cron():
    if request.args.get("secret") != CRON_SECRET:
        return "Forbidden", 403
    try:
        send_reminders()
        return "OK"
    except Exception as e:
        return str(e), 500

@app.route("/")
def index():
    return "Bot is running"

# ========== ЗАПУСК ==========
updater = Updater(token=BOT_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("admin", admin_command))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_message))
dp.add_handler(CallbackQueryHandler(my_subscription, pattern="^my_subscription$"))
dp.add_handler(CallbackQueryHandler(pay, pattern="^pay$"))
dp.add_handler(CallbackQueryHandler(amount, pattern="^amount_|^back_to_main$"))
dp.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_|^back_to_main$"))
dp.add_handler(CallbackQueryHandler(confirm, pattern="^confirm_|^reject_$"))
dp.add_handler(CallbackQueryHandler(manual_select, pattern="^mselect_"))
dp.add_handler(CallbackQueryHandler(manual_extend, pattern="^mextend_"))

# Вебхук
updater.bot.set_webhook(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

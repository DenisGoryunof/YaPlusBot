import os
import json
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# Загружаем переменные окружения (для локального запуска)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
CRON_SECRET = os.getenv("CRON_SECRET")
DATA_FILE = "data.json"
MONTH_PRICE = 100

# ========== Работа с JSON ==========
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
        data["users"][uid] = {
            "subscription_end": "1970-01-01",
            "username": None,
            "first_name": None
        }
    user = data["users"][uid]
    for key, value in kwargs.items():
        if value is not None:
            user[key] = value
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

# ========== Безопасное редактирование сообщений ==========
def safe_edit_message_text(query, text, reply_markup=None):
    """Игнорирует ошибку 'Message is not modified'."""
    try:
        query.edit_message_text(text, reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise

# ========== Клавиатуры ==========
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Оплатить", callback_data="pay")],
        [InlineKeyboardButton("📅 Моя подписка", callback_data="my_subscription")]
    ]
    return InlineKeyboardMarkup(keyboard)

def payment_amount_keyboard():
    keyboard = [
        [InlineKeyboardButton("100 руб", callback_data="amount_100"),
         InlineKeyboardButton("200 руб", callback_data="amount_200")],
        [InlineKeyboardButton("300 руб", callback_data="amount_300"),
         InlineKeyboardButton("500 руб", callback_data="amount_500")],
        [InlineKeyboardButton("🔢 Другая сумма", callback_data="amount_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_confirm_keyboard(user_id, amount):
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{user_id}_{amount}"),
         InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}_{amount}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Установить цену", callback_data="admin_set_price")],
        [InlineKeyboardButton("📋 Список подписчиков", callback_data="admin_list_users")],
        [InlineKeyboardButton("🔧 Продлить вручную", callback_data="admin_manual_extend")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Хэндлеры ==========
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    if update.effective_chat.type == "private":
        update_user(user.id, username=user.username, first_name=user.first_name)
        update.message.reply_text("Добро пожаловать! Используйте меню ниже.",
                                  reply_markup=main_menu_keyboard())

def new_chat_member(update: Update, context: CallbackContext):
    if update.effective_chat.id == GROUP_ID:
        for member in update.message.new_chat_members:
            if member.id != context.bot.id:
                update_user(member.id, username=member.username, first_name=member.first_name)
                context.bot.send_message(
                    member.id,
                    "Вы были добавлены в группу подписчиков. Настройте подписку, нажав /start в личке со мной."
                )

def my_subscription(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    end_date = get_subscription_end(user_id)
    if end_date and end_date >= datetime.now().date():
        text = f"📅 Ваша подписка активна до {end_date.strftime('%d.%m.%Y')}."
    else:
        text = "❗ У вас нет активной подписки. Нажмите «Оплатить», чтобы продлить."
    safe_edit_message_text(query, text, reply_markup=main_menu_keyboard())

def pay(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, "Выберите сумму оплаты:", reply_markup=payment_amount_keyboard())

def send_admin_notification(bot, user_id, amount):
    user = get_user(user_id)
    username = user.get("username", "Unknown")
    text = f"🔔 Пользователь @{username} (ID: {user_id}) запросил оплату на сумму {amount} руб.\nПодтвердить продление?"
    bot.send_message(ADMIN_ID, text, reply_markup=admin_confirm_keyboard(user_id, amount))

def extend_subscription(bot, user_id, amount):
    data = load_data()
    price_per_month = data["settings"]["price_per_month"]
    months = amount // price_per_month
    if months == 0:
        months = 1
    current_end = get_subscription_end(user_id)
    if current_end and current_end >= datetime.now().date():
        new_end = datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    bot.send_message(user_id, f"✅ Ваша подписка продлена до {new_end.strftime('%d.%m.%Y')}.")
    bot.send_message(ADMIN_ID, f"✅ Подписка пользователя {user_id} продлена на {months} мес.")

def amount(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("amount_"):
        amount_str = data.split("_")[1]
        if amount_str == "custom":
            safe_edit_message_text(query, "Введите сумму в рублях (целое число):")
            context.user_data["waiting_for_custom"] = True
        else:
            amount = int(amount_str)
            send_admin_notification(context.bot, query.from_user.id, amount)
            safe_edit_message_text(
                query,
                f"Запрос на оплату {amount} руб. отправлен администратору. Ожидайте подтверждения."
            )
    elif data == "back_to_main":
        safe_edit_message_text(query, "Главное меню:", reply_markup=main_menu_keyboard())

def confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.from_user.id != ADMIN_ID:
        query.answer("У вас нет прав.", show_alert=True)
        return
    data = query.data
    if data.startswith("confirm_"):
        _, user_id_str, amount_str = data.split("_")
        user_id = int(user_id_str)
        amount = int(amount_str)
        extend_subscription(context.bot, user_id, amount)
        safe_edit_message_text(query, f"✅ Подтверждена оплата {amount} руб. для пользователя {user_id}. Подписка продлена.")
    elif data.startswith("reject_"):
        _, user_id_str, amount_str = data.split("_")
        user_id = int(user_id_str)
        amount = int(amount_str)
        context.bot.send_message(
            user_id,
            f"❌ Ваш запрос на оплату {amount} руб. отклонён администратором. Свяжитесь с администратором для уточнения."
        )
        safe_edit_message_text(query, f"❌ Запрос пользователя {user_id} отклонён.")

def admin_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.from_user.id != ADMIN_ID:
        query.answer("У вас нет прав.", show_alert=True)
        return
    data = query.data
    if data == "admin_set_price":
        safe_edit_message_text(query, "Введите новую цену за месяц (в рублях):")
        context.user_data["waiting_for_price"] = True
    elif data == "admin_list_users":
        data_json = load_data()
        users = data_json["users"]
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
        safe_edit_message_text(query, text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        show_users_for_manual(update, context)
    elif data == "back_to_main":
        safe_edit_message_text(query, "Главное меню:", reply_markup=main_menu_keyboard())

def show_users_for_manual(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = load_data()
    users = data["users"]
    if not users:
        safe_edit_message_text(query, "Нет зарегистрированных пользователей.")
        return
    keyboard = []
    for uid, info in users.items():
        if uid == str(ADMIN_ID):
            continue
        username = info.get("username") or info.get("first_name") or uid
        keyboard.append([InlineKeyboardButton(username, callback_data=f"manual_select_{uid}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")])
    safe_edit_message_text(query, "Выберите пользователя для продления:", reply_markup=InlineKeyboardMarkup(keyboard))

def manual_select_user(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.data.split("_")[2]
    context.user_data["manual_user_id"] = user_id
    keyboard = [
        [InlineKeyboardButton("1 месяц", callback_data="manual_months_1")],
        [InlineKeyboardButton("3 месяца", callback_data="manual_months_3")],
        [InlineKeyboardButton("6 месяцев", callback_data="manual_months_6")],
        [InlineKeyboardButton("12 месяцев", callback_data="manual_months_12")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel")]
    ]
    safe_edit_message_text(query, "Выберите количество месяцев:", reply_markup=InlineKeyboardMarkup(keyboard))

def manual_extend_months(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    months = int(query.data.split("_")[2])
    user_id = int(context.user_data.get("manual_user_id"))
    if not user_id:
        safe_edit_message_text(query, "Ошибка: пользователь не выбран.")
        return
    current_end = get_subscription_end(user_id)
    if current_end and current_end >= datetime.now().date():
        new_end = datetime.combine(current_end, datetime.min.time()) + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(user_id, new_end)
    safe_edit_message_text(query, f"✅ Подписка пользователя {user_id} продлена до {new_end.strftime('%d.%m.%Y')}.")
    context.bot.send_message(user_id, f"Администратор продлил вашу подписку до {new_end.strftime('%d.%m.%Y')}.")
    context.user_data.clear()
    query.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

def back_to_admin_panel(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, "Панель администратора:", reply_markup=admin_panel_keyboard())
    context.user_data.clear()

def text_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if update.message and update.message.new_chat_members:
        for member in update.message.new_chat_members:
            if member.id != context.bot.id:
                update_user(member.id, username=member.username, first_name=member.first_name)
                context.bot.send_message(
                    member.id,
                    "Вы были добавлены в группу подписчиков. Настройте подписку, нажав /start в личке со мной."
                )
        return

    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            if amount <= 0:
                raise ValueError
            send_admin_notification(context.bot, user_id, amount)
            update.message.reply_text(f"Запрос на оплату {amount} руб. отправлен администратору. Ожидайте подтверждения.")
        except:
            update.message.reply_text("Пожалуйста, введите целое положительное число.")
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
            update.message.reply_text(f"✅ Цена за месяц установлена: {new_price} руб.")
        except:
            update.message.reply_text("Ошибка: введите целое положительное число.")
        context.user_data["waiting_for_price"] = False
        return

    if update.effective_chat.type == "private":
        update.message.reply_text("Используйте меню ниже.", reply_markup=main_menu_keyboard())

def admin_command(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("У вас нет прав.")
        return
    update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

# ========== Функция отправки напоминаний ==========
def send_reminders():
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
            bot.send_message(uid, text)
            continue
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        if end_date <= tomorrow:
            if end_date < today:
                text = f"⚠️ Ваша подписка истекла {end_date.strftime('%d.%m.%Y')}. Пожалуйста, оплатите, нажав /pay в группе."
            else:
                text = f"⚠️ Ваша подписка истекает {end_date.strftime('%d.%m.%Y')}. Для продления нажмите /pay в группе."
            bot.send_message(uid, text)
    return True

# ========== Flask приложение ==========
app = Flask(__name__)

updater = Updater(token=BOT_TOKEN, use_context=True)
dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("admin", admin_command))
dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_chat_member))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_message))
dp.add_handler(CallbackQueryHandler(my_subscription, pattern="^my_subscription$"))
dp.add_handler(CallbackQueryHandler(pay, pattern="^pay$"))
dp.add_handler(CallbackQueryHandler(amount, pattern="^amount_|^back_to_main$"))
dp.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_|^back_to_main$"))
dp.add_handler(CallbackQueryHandler(confirm, pattern="^confirm_|^reject_$"))
dp.add_handler(CallbackQueryHandler(show_users_for_manual, pattern="^admin_manual_extend$"))
dp.add_handler(CallbackQueryHandler(manual_select_user, pattern="^manual_select_"))
dp.add_handler(CallbackQueryHandler(manual_extend_months, pattern="^manual_months_"))
dp.add_handler(CallbackQueryHandler(back_to_admin_panel, pattern="^back_to_admin_panel$"))

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), updater.bot)
    dp.process_update(update)
    return "ok", 200

@app.route("/cron", methods=["GET"])
def cron():
    secret = request.args.get("secret")
    if secret != CRON_SECRET:
        return "Forbidden", 403
    try:
        send_reminders()
        return "OK", 200
    except Exception as e:
        import traceback
        return traceback.format_exc(), 500

@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200


if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": {}, "settings": {"price_per_month": 100}}, f, indent=2)
    print("data.json created")
    

# ========== Запуск (для Render используется Gunicorn) ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

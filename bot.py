import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        user = update.effective_user
        update_user(user.id, username=user.username, first_name=user.first_name)
        await update.message.reply_text("Добро пожаловать! Используйте меню ниже.", reply_markup=main_menu_keyboard())

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    end_date = get_subscription_end(query.from_user.id)
    text = f"📅 Активна до {end_date.strftime('%d.%m.%Y')}." if end_date and end_date >= datetime.now().date() else "❗ Нет активной подписки. Нажмите «Оплатить»."
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите сумму:", reply_markup=payment_amount_keyboard())

async def amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("amount_"):
        amount_str = data.split("_")[1]
        if amount_str == "custom":
            await query.edit_message_text("Введите сумму (целое число):")
            context.user_data["waiting_for_custom"] = True
        else:
            amount = int(amount_str)
            user = get_user(query.from_user.id)
            username = user.get("username", "Unknown")
            await context.bot.send_message(ADMIN_ID, f"🔔 @{username} (ID: {query.from_user.id}) запросил {amount} руб.", reply_markup=admin_confirm_keyboard(query.from_user.id, amount))
            await query.edit_message_text(f"Запрос на {amount} руб. отправлен админу.")
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет прав.", show_alert=True)
        return
    data = query.data
    if data.startswith("confirm_"):
        _, uid, amt = data.split("_")
        uid, amt = int(uid), int(amt)
        price = load_data()["settings"]["price_per_month"]
        months = max(1, amt // price)
        end_date = get_subscription_end(uid)
        if end_date and end_date >= datetime.now().date():
            new_end = end_date + timedelta(days=30 * months)
        else:
            new_end = datetime.now().date() + timedelta(days=30 * months)
        set_subscription_end(uid, new_end)
        await context.bot.send_message(uid, f"✅ Подписка продлена до {new_end.strftime('%d.%m.%Y')}.")
        await query.edit_message_text(f"✅ Подтверждено {amt} руб. Продлён на {months} мес.")
    elif data.startswith("reject_"):
        _, uid, amt = data.split("_")
        uid, amt = int(uid), int(amt)
        await context.bot.send_message(uid, f"❌ Запрос на {amt} руб. отклонён.")
        await query.edit_message_text(f"❌ Запрос отклонён.")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет прав.", show_alert=True)
        return
    data = query.data
    if data == "admin_set_price":
        await query.edit_message_text("Введите новую цену за месяц (руб):")
        context.user_data["waiting_for_price"] = True
    elif data == "admin_list_users":
        users = load_data()["users"]
        if not users:
            text = "Список подписчиков пуст."
        else:
            lines = []
            for uid, info in users.items():
                end = info.get("subscription_end")
                if end == "1970-01-01" or not end:
                    end = "неактивна"
                else:
                    end = datetime.strptime(end, "%Y-%m-%d").strftime("%d.%m.%Y")
                name = info.get("username") or info.get("first_name") or uid
                lines.append(f"{name}: {end}")
            text = "Подписчики:\n" + "\n".join(lines)
        await query.edit_message_text(text, reply_markup=admin_panel_keyboard())
    elif data == "admin_manual_extend":
        users = load_data()["users"]
        if not users:
            await query.edit_message_text("Нет пользователей.")
            return
        keyboard = []
        for uid, info in users.items():
            if uid == str(ADMIN_ID):
                continue
            name = info.get("username") or info.get("first_name") or uid
            keyboard.append([InlineKeyboardButton(name, callback_data=f"mselect_{uid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
        await query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "back_to_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def manual_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split("_")[1]
    context.user_data["manual_uid"] = uid
    keyboard = [[InlineKeyboardButton(f"{m} мес", callback_data=f"mextend_{m}")] for m in [1, 3, 6, 12]]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
    await query.edit_message_text("Выберите срок:", reply_markup=InlineKeyboardMarkup(keyboard))

async def manual_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    months = int(query.data.split("_")[1])
    uid = int(context.user_data.get("manual_uid"))
    if not uid:
        await query.edit_message_text("Ошибка.")
        return
    end_date = get_subscription_end(uid)
    if end_date and end_date >= datetime.now().date():
        new_end = end_date + timedelta(days=30 * months)
    else:
        new_end = datetime.now().date() + timedelta(days=30 * months)
    set_subscription_end(uid, new_end)
    await context.bot.send_message(uid, f"Админ продлил подписку до {new_end.strftime('%d.%m.%Y')}.")
    await query.edit_message_text(f"✅ Продлён до {new_end.strftime('%d.%m.%Y')}.")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            if amount <= 0: raise ValueError
            user = get_user(user_id)
            username = user.get("username", "Unknown")
            await context.bot.send_message(ADMIN_ID, f"🔔 @{username} (ID: {user_id}) запросил {amount} руб.", reply_markup=admin_confirm_keyboard(user_id, amount))
            await update.message.reply_text(f"Запрос на {amount} руб. отправлен админу.")
        except:
            await update.message.reply_text("Введите число больше 0.")
        context.user_data["waiting_for_custom"] = False
    elif user_id == ADMIN_ID and context.user_data.get("waiting_for_price"):
        try:
            new_price = int(text)
            if new_price <= 0: raise ValueError
            data = load_data()
            data["settings"]["price_per_month"] = new_price
            save_data(data)
            await update.message.reply_text(f"✅ Цена установлена: {new_price} руб/мес.")
        except:
            await update.message.reply_text("Ошибка: введите число.")
        context.user_data["waiting_for_price"] = False
    elif update.effective_chat.type == "private":
        await update.message.reply_text("Используйте меню.", reply_markup=main_menu_keyboard())

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет прав.")
        return
    await update.message.reply_text("Панель администратора:", reply_markup=admin_panel_keyboard())

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Запуск бота...")
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация хэндлеров
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_handler(CallbackQueryHandler(my_subscription, pattern="^my_subscription$"))
    app.add_handler(CallbackQueryHandler(pay, pattern="^pay$"))
    app.add_handler(CallbackQueryHandler(amount, pattern="^amount_|^back_to_main$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_|^back_to_main$"))
    app.add_handler(CallbackQueryHandler(confirm, pattern="^confirm_|^reject_$"))
    app.add_handler(CallbackQueryHandler(manual_select, pattern="^mselect_"))
    app.add_handler(CallbackQueryHandler(manual_extend, pattern="^mextend_"))
    
    # Запуск polling
    print("✅ Бот запущен. Ожидание сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

# Минимальный веб-сервер для Health Check
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 10000))), HealthHandler)
    server.serve_forever()

# Запускаем health сервер в фоне
Thread(target=run_health_server, daemon=True).start()

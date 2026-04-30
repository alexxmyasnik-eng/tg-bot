import telebot
from telebot import types
import json
import os

# ========================
# НАСТРОЙКИ
# ========================
BOT_TOKEN = "ВСТАВЬТЕ_НОВЫЙ_ТОКЕН_СЮДА"  # ← Замените после сброса старого!

# Файл для хранения модераторов
MODERATORS_FILE = "moderators.json"

# ========================
# ХРАНЕНИЕ ДАННЫХ
# ========================
def load_moderators():
    if os.path.exists(MODERATORS_FILE):
        with open(MODERATORS_FILE, "r") as f:
            return json.load(f)
    return {"admins": [], "moderators": []}

def save_moderators(data):
    with open(MODERATORS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_all_mods():
    data = load_moderators()
    return data["admins"] + data["moderators"]

def is_admin(user_id):
    data = load_moderators()
    return user_id in data["admins"]

def is_moderator(user_id):
    return user_id in get_all_mods()

# Словарь ожидающих фото: {file_id: {"user_id": ..., "user_name": ..., "message_id": ...}}
pending_photos = {}
# Словарь для хранения состояния модератора при отклонении: {mod_id: file_id}
waiting_rejection_reason = {}

# ========================
# БОТ
# ========================
bot = telebot.TeleBot(BOT_TOKEN)

# ── /start ──────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    if is_moderator(uid):
        bot.send_message(uid,
            "👋 Привет, модератор!\n\n"
            "Команды:\n"
            "/pending — список фото на проверке\n"
            "/addmod @username ID — добавить модератора (только для администраторов)\n"
            "/listmods — список модераторов\n"
            "/removemod ID — удалить модератора (только для администраторов)"
        )
    else:
        bot.send_message(uid,
            "👋 Привет!\n\n"
            "Отправь мне фотографию, и она попадёт на проверку к модератору.\n"
            "Ты получишь уведомление о решении."
        )

# ── Настройка первого администратора ────────────────────
@bot.message_handler(commands=["setup"])
def cmd_setup(message):
    """Первоначальная настройка — добавить себя как админа."""
    data = load_moderators()
    uid = message.from_user.id
    if len(data["admins"]) == 0:
        data["admins"].append(uid)
        save_moderators(data)
        bot.send_message(uid, f"✅ Вы добавлены как первый администратор! Ваш ID: {uid}")
    else:
        if is_admin(uid):
            bot.send_message(uid, f"Вы уже администратор. Ваш ID: {uid}")
        else:
            bot.send_message(uid, "❌ Администратор уже установлен.")

# ── Добавить модератора ─────────────────────────────────
@bot.message_handler(commands=["addmod"])
def cmd_addmod(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ Только администраторы могут добавлять модераторов.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(uid, "Использование: /addmod 123456789\nГде число — Telegram ID нового модератора.")
        return

    try:
        new_mod_id = int(parts[1])
    except ValueError:
        bot.send_message(uid, "❌ Неверный ID. Используйте числовой Telegram ID.")
        return

    data = load_moderators()
    if new_mod_id in data["admins"] or new_mod_id in data["moderators"]:
        bot.send_message(uid, "ℹ️ Этот пользователь уже является модератором или администратором.")
        return

    data["moderators"].append(new_mod_id)
    save_moderators(data)
    bot.send_message(uid, f"✅ Пользователь с ID {new_mod_id} добавлен как модератор.")
    try:
        bot.send_message(new_mod_id, "🎉 Вы назначены модератором! Напишите /start чтобы увидеть доступные команды.")
    except:
        pass

# ── Удалить модератора ──────────────────────────────────
@bot.message_handler(commands=["removemod"])
def cmd_removemod(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ Только администраторы могут удалять модераторов.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(uid, "Использование: /removemod 123456789")
        return

    try:
        rem_id = int(parts[1])
    except ValueError:
        bot.send_message(uid, "❌ Неверный ID.")
        return

    data = load_moderators()
    if rem_id in data["moderators"]:
        data["moderators"].remove(rem_id)
        save_moderators(data)
        bot.send_message(uid, f"✅ Модератор {rem_id} удалён.")
    elif rem_id in data["admins"]:
        bot.send_message(uid, "❌ Нельзя удалить администратора через эту команду.")
    else:
        bot.send_message(uid, "❌ Такой модератор не найден.")

# ── Список модераторов ──────────────────────────────────
@bot.message_handler(commands=["listmods"])
def cmd_listmods(message):
    uid = message.from_user.id
    if not is_moderator(uid):
        bot.send_message(uid, "❌ Нет доступа.")
        return
    data = load_moderators()
    text = "👥 *Список модераторов*\n\n"
    text += f"*Администраторы:* {', '.join(map(str, data['admins'])) or 'нет'}\n"
    text += f"*Модераторы:* {', '.join(map(str, data['moderators'])) or 'нет'}"
    bot.send_message(uid, text, parse_mode="Markdown")

# ── Список фото на проверке ─────────────────────────────
@bot.message_handler(commands=["pending"])
def cmd_pending(message):
    uid = message.from_user.id
    if not is_moderator(uid):
        bot.send_message(uid, "❌ Нет доступа.")
        return
    if not pending_photos:
        bot.send_message(uid, "📭 Нет фотографий на проверке.")
        return
    bot.send_message(uid, f"📋 Фотографий на проверке: {len(pending_photos)}\nОтображаю все...")
    for fid, info in list(pending_photos.items()):
        send_photo_to_mod(uid, fid, info)

# ── Отправить фото модератору ───────────────────────────
def send_photo_to_mod(mod_id, file_id, info):
    user_display = info.get("user_name", str(info["user_id"]))
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"approve_{file_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{file_id}")
    )
    try:
        bot.send_photo(
            mod_id,
            file_id,
            caption=f"👤 От: {user_display} (ID: {info['user_id']})\n📸 Фото на проверке",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки модератору {mod_id}: {e}")

# ── Получение фото от пользователя ─────────────────────
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id

    # Если модератор ввёл причину отклонения через текст — игнорируем фото
    if uid in waiting_rejection_reason:
        bot.send_message(uid, "⚠️ Сначала введите причину отклонения текстом.")
        return

    file_id = message.photo[-1].file_id  # Берём наилучшее качество
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    pending_photos[file_id] = {
        "user_id": uid,
        "user_name": user_name,
    }

    bot.send_message(uid, "📤 Ваше фото отправлено на проверку. Ожидайте решения модератора.")

    # Отправить всем модераторам
    mods = get_all_mods()
    if not mods:
        bot.send_message(uid, "⚠️ Модераторы ещё не назначены. Свяжитесь с администратором.")
        return

    for mod_id in mods:
        send_photo_to_mod(mod_id, file_id, pending_photos[file_id])

# ── Обработка кнопок ────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_decision(call):
    mod_id = call.from_user.id
    if not is_moderator(mod_id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав модератора.")
        return

    action, file_id = call.data.split("_", 1)
    info = pending_photos.get(file_id)

    if not info:
        bot.answer_callback_query(call.id, "⚠️ Это фото уже было обработано.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        return

    if action == "approve":
        user_id = info["user_id"]
        del pending_photos[file_id]

        # Уведомить пользователя
        try:
            bot.send_message(user_id, "✅ Ваше фото *принято* модератором!", parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка уведомления пользователя: {e}")

        # Убрать кнопки у всех модераторов
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=f"✅ *Принято* модератором @{call.from_user.username or mod_id}\n"
                    f"👤 Пользователь: {info['user_name']} (ID: {info['user_id']})",
            parse_mode="Markdown",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, "✅ Фото принято!")

    elif action == "reject":
        # Запросить причину
        waiting_rejection_reason[mod_id] = {
            "file_id": file_id,
            "chat_id": call.message.chat.id,
            "message_id": call.message.message_id
        }
        bot.answer_callback_query(call.id, "Введите причину отклонения")
        bot.send_message(mod_id, "✏️ Напишите причину отклонения фото:")

# ── Обработка причины отклонения ───────────────────────
@bot.message_handler(func=lambda m: m.from_user.id in waiting_rejection_reason, content_types=["text"])
def handle_rejection_reason(message):
    mod_id = message.from_user.id
    reason = message.text
    state = waiting_rejection_reason.pop(mod_id)

    file_id = state["file_id"]
    info = pending_photos.get(file_id)

    if not info:
        bot.send_message(mod_id, "⚠️ Это фото уже было обработано другим модератором.")
        return

    user_id = info["user_id"]
    del pending_photos[file_id]

    # Уведомить пользователя с причиной
    try:
        bot.send_message(
            user_id,
            f"❌ Ваше фото *отклонено*.\n\n📝 *Причина:* {reason}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")

    # Обновить сообщение у модератора
    try:
        bot.edit_message_caption(
            chat_id=state["chat_id"],
            message_id=state["message_id"],
            caption=f"❌ *Отклонено* модератором @{message.from_user.username or mod_id}\n"
                    f"👤 Пользователь: {info['user_name']} (ID: {info['user_id']})\n"
                    f"📝 Причина: {reason}",
            parse_mode="Markdown",
            reply_markup=None
        )
    except:
        pass

    bot.send_message(mod_id, "✅ Решение отправлено пользователю.")

# ── Запуск ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Бот запущен...")
    print("Первый запуск: напишите боту /setup чтобы стать администратором")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

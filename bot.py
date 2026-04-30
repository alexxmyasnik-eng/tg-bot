import telebot
from telebot import types
import json
import os
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MODERATORS_FILE = "moderators.json"

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
    return user_id in load_moderators()["admins"]

def is_moderator(user_id):
    return user_id in get_all_mods()

# Хранилище заявок
# submissions[sid] = {"user_id": ..., "user_name": ..., "photos": [file_id, ...], "status": "pending"}
submissions = {}
sub_counter = [0]

# Буфер для группировки фото от одного пользователя
# buffer[user_id] = {"photos": [...], "timer": timestamp}
photo_buffer = {}
BUFFER_SECONDS = 3  # ждём 3 секунды после последнего фото

waiting_rejection_reason = {}

def next_sid():
    sub_counter[0] += 1
    return str(sub_counter[0])

bot = telebot.TeleBot(BOT_TOKEN)

# ── Команды ──────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    if is_moderator(uid):
        bot.send_message(uid,
            "👋 Привет, модератор!\n\n"
            "/pending — заявки на проверке\n"
            "/addmod ID — добавить модератора\n"
            "/removemod ID — удалить модератора\n"
            "/listmods — список модераторов"
        )
    else:
        bot.send_message(uid,
            "👋 Привет!\n\n"
            "Отправь фотографии (можно сразу несколько) — они попадут на проверку.\n"
            "Ты получишь уведомление о решении."
        )

@bot.message_handler(commands=["setup"])
def cmd_setup(message):
    data = load_moderators()
    uid = message.from_user.id
    if len(data["admins"]) == 0:
        data["admins"].append(uid)
        save_moderators(data)
        bot.send_message(uid, f"✅ Вы первый администратор! Ваш ID: {uid}")
    elif is_admin(uid):
        bot.send_message(uid, f"Вы уже администратор. ID: {uid}")
    else:
        bot.send_message(uid, "❌ Администратор уже установлен.")

@bot.message_handler(commands=["addmod"])
def cmd_addmod(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ Только администраторы могут добавлять модераторов.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(uid, "Использование: /addmod 123456789")
        return
    try:
        new_id = int(parts[1])
    except ValueError:
        bot.send_message(uid, "❌ Неверный ID.")
        return
    data = load_moderators()
    if new_id in data["admins"] or new_id in data["moderators"]:
        bot.send_message(uid, "ℹ️ Уже модератор.")
        return
    data["moderators"].append(new_id)
    save_moderators(data)
    bot.send_message(uid, f"✅ {new_id} добавлен как модератор.")
    try:
        bot.send_message(new_id, "🎉 Вы назначены модератором! Напишите /start.")
    except:
        pass

@bot.message_handler(commands=["removemod"])
def cmd_removemod(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ Нет прав.")
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
    else:
        bot.send_message(uid, "❌ Не найден.")

@bot.message_handler(commands=["listmods"])
def cmd_listmods(message):
    if not is_moderator(message.from_user.id):
        bot.send_message(message.from_user.id, "❌ Нет доступа.")
        return
    data = load_moderators()
    text = (f"👥 *Модераторы*\n"
            f"Админы: {', '.join(map(str, data['admins'])) or 'нет'}\n"
            f"Модераторы: {', '.join(map(str, data['moderators'])) or 'нет'}")
    bot.send_message(message.from_user.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["pending"])
def cmd_pending(message):
    uid = message.from_user.id
    if not is_moderator(uid):
        bot.send_message(uid, "❌ Нет доступа.")
        return
    pending = {sid: s for sid, s in submissions.items() if s["status"] == "pending"}
    if not pending:
        bot.send_message(uid, "📭 Нет заявок на проверке.")
        return
    bot.send_message(uid, f"📋 Заявок на проверке: {len(pending)}")
    for sid, sub in pending.items():
        send_submission_to_mod(uid, sid, sub)

# ── Приём фото от пользователя ───────────────────────────

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id

    if uid in waiting_rejection_reason:
        bot.send_message(uid, "⚠️ Сначала введите причину отклонения текстом.")
        return

    file_id = message.photo[-1].file_id
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    if uid not in photo_buffer:
        photo_buffer[uid] = {"photos": [], "user_name": user_name, "notified": False}

    photo_buffer[uid]["photos"].append(file_id)
    photo_buffer[uid]["last_time"] = time.time()

    # Уведомляем пользователя только один раз
    if not photo_buffer[uid]["notified"]:
        photo_buffer[uid]["notified"] = True
        bot.send_message(uid, "📤 Получаю фото... Отправьте все нужные и подождите немного.")

    # Запускаем отложенную отправку
    import threading
    t = threading.Timer(BUFFER_SECONDS, flush_buffer, args=[uid])
    t.daemon = True
    t.start()

def flush_buffer(uid):
    if uid not in photo_buffer:
        return

    buf = photo_buffer[uid]
    # Проверяем что прошло достаточно времени с последнего фото
    if time.time() - buf["last_time"] < BUFFER_SECONDS - 0.1:
        return  # Ещё идут фото, другой таймер подхватит

    photos = buf["photos"]
    user_name = buf["user_name"]
    del photo_buffer[uid]

    sid = next_sid()
    submissions[sid] = {
        "user_id": uid,
        "user_name": user_name,
        "photos": photos,
        "status": "pending"
    }

    bot.send_message(uid, f"✅ Заявка #{sid} отправлена на проверку ({len(photos)} фото). Ожидайте решения.")

    mods = get_all_mods()
    if not mods:
        bot.send_message(uid, "⚠️ Модераторы не назначены.")
        return

    for mod_id in mods:
        send_submission_to_mod(mod_id, sid, submissions[sid])

# ── Отправка заявки модератору ───────────────────────────

def send_submission_to_mod(mod_id, sid, sub):
    photos = sub["photos"]
    user_name = sub["user_name"]
    user_id = sub["user_id"]
    count = len(photos)

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(f"✅ Принять все ({count})", callback_data=f"a_{sid}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"r_{sid}")
    )

    try:
        if count == 1:
            # Одно фото — отправляем с кнопками сразу
            bot.send_photo(
                mod_id,
                photos[0],
                caption=f"👤 {user_name} (ID: {user_id})\n📸 1 фото | Заявка #{sid}",
                reply_markup=markup
            )
        else:
            # Несколько фото — отправляем альбомом, потом кнопки
            media = [types.InputMediaPhoto(pid) for pid in photos]
            media[0].caption = f"👤 {user_name} (ID: {user_id}) | {count} фото | Заявка #{sid}"
            bot.send_media_group(mod_id, media)
            bot.send_message(
                mod_id,
                f"☝️ Заявка #{sid} от {user_name} — {count} фото",
                reply_markup=markup
            )
    except Exception as e:
        print(f"Ошибка отправки модератору {mod_id}: {e}")

# ── Обработка кнопок ─────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("a_") or call.data.startswith("r_"))
def handle_decision(call):
    mod_id = call.from_user.id
    if not is_moderator(mod_id):
        bot.answer_callback_query(call.id, "❌ Нет прав.")
        return

    action, sid = call.data.split("_", 1)
    sub = submissions.get(sid)

    if not sub or sub["status"] != "pending":
        bot.answer_callback_query(call.id, "⚠️ Заявка уже обработана.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        return

    if action == "a":
        sub["status"] = "approved"
        try:
            bot.send_message(sub["user_id"],
                f"✅ Ваша заявка #{sid} *принята!*",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Ошибка уведомления: {e}")
        try:
            bot.edit_message_text(
                f"✅ Заявка #{sid} принята\n👤 {sub['user_name']} | {len(sub['photos'])} фото",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
        except:
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except:
                pass
        bot.answer_callback_query(call.id, "✅ Принято!")

    elif action == "r":
        waiting_rejection_reason[mod_id] = {
            "sid": sid,
            "chat_id": call.message.chat.id,
            "message_id": call.message.message_id
        }
        bot.answer_callback_query(call.id, "Введите причину")
        bot.send_message(mod_id, f"✏️ Причина отклонения заявки #{sid}:")

# ── Причина отклонения ───────────────────────────────────

@bot.message_handler(func=lambda m: m.from_user.id in waiting_rejection_reason, content_types=["text"])
def handle_rejection_reason(message):
    mod_id = message.from_user.id
    reason = message.text
    state = waiting_rejection_reason.pop(mod_id)

    sid = state["sid"]
    sub = submissions.get(sid)

    if not sub or sub["status"] != "pending":
        bot.send_message(mod_id, "⚠️ Заявка уже обработана.")
        return

    sub["status"] = "rejected"

    try:
        bot.send_message(
            sub["user_id"],
            f"❌ Заявка #{sid} *отклонена*\n\n📝 *Причина:* {reason}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка уведомления: {e}")

    try:
        bot.edit_message_text(
            f"❌ Заявка #{sid} отклонена\n👤 {sub['user_name']}\n📝 {reason}",
            state["chat_id"],
            state["message_id"],
            reply_markup=None
        )
    except:
        try:
            bot.edit_message_reply_markup(state["chat_id"], state["message_id"], reply_markup=None)
        except:
            pass

    bot.send_message(mod_id, "✅ Решение отправлено.")

# ── Запуск ───────────────────────────────────────────────

if __name__ == "__main__":
    print("🤖 Бот запущен...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

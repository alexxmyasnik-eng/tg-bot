import telebot
from telebot import types
import json
import os
import time
import threading

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MODERATORS_FILE = "moderators.json"
REQUIRED_PHOTOS = 25  # Минимум фото для отправки заявки
CHANNEL_USERNAME = "Zonvate"  # Канал без @

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
submissions = {}
sub_counter = [0]

# Буфер фото от пользователей
# buffer[user_id] = {"photos": [...], "user_name": ..., "last_time": ..., "timer": ..., "status_msg_id": ...}
photo_buffer = {}
BUFFER_SECONDS = 4

waiting_rejection_reason = {}

def next_sid():
    sub_counter[0] += 1
    return str(sub_counter[0])

bot = telebot.TeleBot(BOT_TOKEN)

# ── Проверка подписки ────────────────────────────────────

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def send_subscribe_prompt(uid):
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME}"))
    markup.row(types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub"))
    bot.send_message(
        uid,
        "👋 Привет!\n\n"
        "Для использования бота необходимо подписаться на наш канал.\n\n"
        "1️⃣ Нажми *Подписаться на канал*\n"
        "2️⃣ Нажми *Проверить подписку*",
        parse_mode="Markdown",
        reply_markup=markup
    )

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
    elif not is_subscribed(uid):
        send_subscribe_prompt(uid)
    else:
        bot.send_message(uid,
            f"👋 Привет!\n\n"
            f"Для отправки заявки нужно прислать минимум {REQUIRED_PHOTOS} фотографий.\n"
            f"Отправляй их подряд — бот сам их все соберёт."
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

    # Проверка подписки для обычных пользователей
    if not is_moderator(uid) and not is_subscribed(uid):
        send_subscribe_prompt(uid)
        return

    file_id = message.photo[-1].file_id
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    if uid not in photo_buffer:
        photo_buffer[uid] = {
            "photos": [],
            "user_name": user_name,
            "last_time": 0,
            "status_msg_id": None,
            "timer": None
        }

    buf = photo_buffer[uid]
    buf["photos"].append(file_id)
    buf["last_time"] = time.time()
    count = len(buf["photos"])
    remaining = REQUIRED_PHOTOS - count

    # Отменяем предыдущий таймер
    if buf["timer"] is not None:
        buf["timer"].cancel()

    if remaining > 0:
        # Обновляем или отправляем статусное сообщение
        status_text = (
            f"📷 Получено фото: *{count}*\n"
            f"⏳ Осталось добавить: *{remaining}*\n\n"
            f"Продолжай отправлять фото..."
        )
        try:
            if buf["status_msg_id"]:
                bot.edit_message_text(
                    status_text,
                    uid,
                    buf["status_msg_id"],
                    parse_mode="Markdown"
                )
            else:
                msg = bot.send_message(uid, status_text, parse_mode="Markdown")
                buf["status_msg_id"] = msg.message_id
        except:
            try:
                msg = bot.send_message(uid, status_text, parse_mode="Markdown")
                buf["status_msg_id"] = msg.message_id
            except:
                pass

        # Таймер — если пользователь перестал слать фото но не набрал 25
        t = threading.Timer(BUFFER_SECONDS, check_incomplete, args=[uid])
        t.daemon = True
        buf["timer"] = t
        t.start()

    else:
        # Набрано 25+ фото — отправляем заявку
        try:
            if buf["status_msg_id"]:
                bot.edit_message_text(
                    f"✅ Все {count} фото получены! Отправляю на проверку...",
                    uid,
                    buf["status_msg_id"]
                )
        except:
            pass

        # Таймер чтобы дать телеграму время доставить все фото
        t = threading.Timer(BUFFER_SECONDS, flush_buffer, args=[uid])
        t.daemon = True
        buf["timer"] = t
        t.start()

def check_incomplete(uid):
    """Вызывается если пользователь перестал слать фото, но не набрал минимум."""
    if uid not in photo_buffer:
        return
    buf = photo_buffer[uid]
    # Если за это время пришли ещё фото — другой таймер разберётся
    if time.time() - buf["last_time"] < BUFFER_SECONDS - 0.1:
        return
    count = len(buf["photos"])
    if count >= REQUIRED_PHOTOS:
        return  # flush_buffer уже запущен
    remaining = REQUIRED_PHOTOS - count
    try:
        status_text = (
            f"📷 Сейчас у тебя: *{count}* фото\n"
            f"❗ Нужно ещё: *{remaining}*\n\n"
            f"Отправь ещё фото чтобы завершить заявку."
        )
        if buf["status_msg_id"]:
            bot.edit_message_text(status_text, uid, buf["status_msg_id"], parse_mode="Markdown")
        else:
            msg = bot.send_message(uid, status_text, parse_mode="Markdown")
            buf["status_msg_id"] = msg.message_id
    except:
        pass

def flush_buffer(uid):
    """Собирает все фото и отправляет заявку модераторам."""
    if uid not in photo_buffer:
        return
    buf = photo_buffer[uid]
    if time.time() - buf["last_time"] < BUFFER_SECONDS - 0.1:
        return

    photos = buf["photos"]
    user_name = buf["user_name"]
    status_msg_id = buf["status_msg_id"]
    del photo_buffer[uid]

    sid = next_sid()
    submissions[sid] = {
        "user_id": uid,
        "user_name": user_name,
        "photos": photos,
        "status": "pending"
    }

    try:
        if status_msg_id:
            bot.edit_message_text(
                f"✅ Заявка *#{sid}* отправлена на проверку ({len(photos)} фото).\nОжидай решения модератора.",
                uid,
                status_msg_id,
                parse_mode="Markdown"
            )
        else:
            bot.send_message(uid, f"✅ Заявка *#{sid}* отправлена на проверку ({len(photos)} фото).", parse_mode="Markdown")
    except:
        bot.send_message(uid, f"✅ Заявка *#{sid}* отправлена на проверку ({len(photos)} фото).", parse_mode="Markdown")

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
        types.InlineKeyboardButton(f"✅ Принять ({count} фото)", callback_data=f"a_{sid}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"r_{sid}")
    )

    try:
        # Telegram позволяет максимум 10 фото в альбоме
        # Отправляем по 10, последняя группа с кнопками
        chunks = [photos[i:i+10] for i in range(0, count, 10)]

        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            media = [types.InputMediaPhoto(fid) for fid in chunk]

            if i == 0:
                media[0].caption = f"👤 {user_name} (ID: {user_id}) | Заявка #{sid} | {count} фото"

            if is_last and len(chunk) == 1:
                # Последний чанк из 1 фото — отправляем с кнопками
                bot.send_photo(mod_id, chunk[0],
                    caption=media[0].caption if i == 0 else f"Заявка #{sid} — продолжение",
                    reply_markup=markup
                )
            else:
                bot.send_media_group(mod_id, media)

        # Если последний чанк был больше 1 — отправляем кнопки отдельным сообщением
        if len(chunks[-1]) > 1:
            bot.send_message(
                mod_id,
                f"☝️ Заявка *#{sid}* от {user_name} — {count} фото",
                reply_markup=markup,
                parse_mode="Markdown"
            )

    except Exception as e:
        print(f"Ошибка отправки модератору {mod_id}: {e}")

# ── Обработка кнопок ─────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def handle_check_sub(call):
    uid = call.from_user.id
    if is_subscribed(uid):
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(
            uid,
            f"👋 Привет!\n\n"
            f"Для отправки заявки нужно прислать минимум {REQUIRED_PHOTOS} фотографий.\n"
            f"Отправляй их подряд — бот сам их все соберёт."
        )
    else:
        bot.answer_callback_query(call.id, "❌ Вы ещё не подписаны!", show_alert=True)

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
                f"✅ Заявка *#{sid}* принята! Поздравляем 🎉",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Ошибка уведомления: {e}")
        try:
            bot.edit_message_text(
                f"✅ Заявка #{sid} *принята*\n👤 {sub['user_name']} | {len(sub['photos'])} фото",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown",
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
        bot.send_message(mod_id, f"✏️ Причина отклонения заявки *#{sid}*:", parse_mode="Markdown")

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
            f"❌ Заявка *#{sid}* отклонена\n\n📝 *Причина:* {reason}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка уведомления: {e}")

    try:
        bot.edit_message_text(
            f"❌ Заявка #{sid} *отклонена*\n👤 {sub['user_name']}\n📝 {reason}",
            state["chat_id"],
            state["message_id"],
            parse_mode="Markdown",
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

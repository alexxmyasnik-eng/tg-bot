import telebot
from telebot import types
import json
import os

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
    data = load_moderators()
    return user_id in data["admins"]

def is_moderator(user_id):
    return user_id in get_all_mods()

pending_photos = {}
photo_counter = [0]
waiting_rejection_reason = {}

def next_id():
    photo_counter[0] += 1
    return str(photo_counter[0])

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    if is_moderator(uid):
        bot.send_message(uid,
            "👋 Привет, модератор!\n\n"
            "Команды:\n"
            "/pending — фото на проверке\n"
            "/addmod ID — добавить модератора\n"
            "/removemod ID — удалить модератора\n"
            "/listmods — список модераторов"
        )
    else:
        bot.send_message(uid,
            "👋 Привет!\n\n"
            "Отправь мне фотографии — она попадёт на проверку к модератору.\n"
            "Ты получишь уведомление о решении."
        )

@bot.message_handler(commands=["setup"])
def cmd_setup(message):
    data = load_moderators()
    uid = message.from_user.id
    if len(data["admins"]) == 0:
        data["admins"].append(uid)
        save_moderators(data)
        bot.send_message(uid, f"✅ Вы добавлены как первый администратор!\nВаш ID: {uid}")
    else:
        if is_admin(uid):
            bot.send_message(uid, f"Вы уже администратор. Ваш ID: {uid}")
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
        new_mod_id = int(parts[1])
    except ValueError:
        bot.send_message(uid, "❌ Неверный ID.")
        return
    data = load_moderators()
    if new_mod_id in data["admins"] or new_mod_id in data["moderators"]:
        bot.send_message(uid, "ℹ️ Этот пользователь уже модератор или администратор.")
        return
    data["moderators"].append(new_mod_id)
    save_moderators(data)
    bot.send_message(uid, f"✅ Пользователь {new_mod_id} добавлен как модератор.")
    try:
        bot.send_message(new_mod_id, "🎉 Вы назначены модератором! Напишите /start чтобы начать.")
    except:
        pass

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
        bot.send_message(uid, "❌ Нельзя удалить администратора.")
    else:
        bot.send_message(uid, "❌ Такой модератор не найден.")

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

@bot.message_handler(commands=["pending"])
def cmd_pending(message):
    uid = message.from_user.id
    if not is_moderator(uid):
        bot.send_message(uid, "❌ Нет доступа.")
        return
    if not pending_photos:
        bot.send_message(uid, "📭 Нет фотографий на проверке.")
        return
    bot.send_message(uid, f"📋 Фотографий на проверке: {len(pending_photos)}")
    for pid, info in list(pending_photos.items()):
        send_photo_to_mod(uid, pid, info)

def send_photo_to_mod(mod_id, pid, info):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"a_{pid}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"r_{pid}")
    )
    try:
        bot.send_photo(
            mod_id,
            info["file_id"],
            caption=f"👤 От: {info['user_name']} (ID: {info['user_id']})\n📸 Фото на проверке",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки модератору {mod_id}: {e}")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    uid = message.from_user.id
    if uid in waiting_rejection_reason:
        bot.send_message(uid, "⚠️ Сначала введите причину отклонения текстом.")
        return

    file_id = message.photo[-1].file_id
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    pid = next_id()
    pending_photos[pid] = {
        "file_id": file_id,
        "user_id": uid,
        "user_name": user_name,
    }

    bot.send_message(uid, "📤 Ваше фото отправлено на проверку. Ожидайте решения.")

    mods = get_all_mods()
    if not mods:
        bot.send_message(uid, "⚠️ Модераторы ещё не назначены.")
        return

    for mod_id in mods:
        send_photo_to_mod(mod_id, pid, pending_photos[pid])

@bot.callback_query_handler(func=lambda call: call.data.startswith("a_") or call.data.startswith("r_"))
def handle_decision(call):
    mod_id = call.from_user.id
    if not is_moderator(mod_id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав модератора.")
        return

    parts = call.data.split("_", 1)
    action, pid = parts[0], parts[1]
    info = pending_photos.get(pid)

    if not info:
        bot.answer_callback_query(call.id, "⚠️ Фото уже обработано.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        return

    if action == "a":
        user_id = info["user_id"]
        del pending_photos[pid]
        try:
            bot.send_message(user_id, "✅ Ваше фото *принято* модератором!", parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка уведомления: {e}")
        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=f"✅ *Принято*\n👤 {info['user_name']} (ID: {info['user_id']})",
                parse_mode="Markdown",
                reply_markup=None
            )
        except:
            pass
        bot.answer_callback_query(call.id, "✅ Принято!")

    elif action == "r":
        waiting_rejection_reason[mod_id] = {
            "pid": pid,
            "chat_id": call.message.chat.id,
            "message_id": call.message.message_id
        }
        bot.answer_callback_query(call.id, "Введите причину")
        bot.send_message(mod_id, "✏️ Напишите причину отклонения:")

@bot.message_handler(func=lambda m: m.from_user.id in waiting_rejection_reason, content_types=["text"])
def handle_rejection_reason(message):
    mod_id = message.from_user.id
    reason = message.text
    state = waiting_rejection_reason.pop(mod_id)

    pid = state["pid"]
    info = pending_photos.get(pid)

    if not info:
        bot.send_message(mod_id, "⚠️ Фото уже обработано другим модератором.")
        return

    user_id = info["user_id"]
    del pending_photos[pid]

    try:
        bot.send_message(
            user_id,
            f"❌ Ваше фото *отклонено*.\n\n📝 *Причина:* {reason}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка уведомления: {e}")

    try:
        bot.edit_message_caption(
            chat_id=state["chat_id"],
            message_id=state["message_id"],
            caption=f"❌ *Отклонено*\n👤 {info['user_name']} (ID: {info['user_id']})\n📝 Причина: {reason}",
            parse_mode="Markdown",
            reply_markup=None
        )
    except:
        pass

    bot.send_message(mod_id, "✅ Решение отправлено пользователю.")

if __name__ == "__main__":
    print("🤖 Бот запущен...")
    print("Первый запуск: напишите боту /setup чтобы стать администратором")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

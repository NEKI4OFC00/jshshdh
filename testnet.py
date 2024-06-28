import telebot
from telebot import types
import sqlite3
import random
import string
from datetime import datetime, timedelta
import threading
import os
import time

# Замените на ваш токен бота
BOT_TOKEN = '7219521716:AAEvgwERJ0hD245gbpXgyUROhSVzmW-DxU4'

# ID администраторов бота
ADMIN_IDS = [6665308361, 7168398511]
REPORT_ADMIN_ID = 6665308361  # ID администратора для получения жалоб

bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к базе данных SQLite
conn = sqlite3.connect('referrals.db', check_same_thread=False)

# Инициализация таблиц в базе данных
with conn:
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            invited_count INTEGER DEFAULT 0,
            first_time BOOLEAN DEFAULT 1,
            start_time TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            duration INTEGER,
            used BOOLEAN DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_promotions (
            user_id INTEGER PRIMARY KEY,
            end_time TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            reason TEXT
        )
    ''')

# Генерация промокода
def generate_promocode(prefix):
    code = prefix + ''.join(random.choice(string.ascii_uppercase) for _ in range(5))
    code += random.choice(string.digits + '#&!?')
    return code

# Сохранение данных пользователей в файл
def save_user_data():
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_promotions')
    users = cursor.fetchall()
    with open('user_data.txt', 'w') as f:
        for user in users:
            user_id, end_time = user
            f.write(f'{user_id},{end_time}\n')

# Загрузка данных пользователей из файла
def load_user_data():
    file_path = 'user_data.txt'
    if os.path.exists(file_path):
        cursor = conn.cursor()
        with open(file_path, 'r') as f:
            for line in f:
                user_id, end_time = line.strip().split(',')
                cursor.execute('INSERT OR REPLACE INTO user_promotions (user_id, end_time) VALUES (?, ?)', (user_id, end_time))
        conn.commit()
    else:
        print(f"File {file_path} does not exist")

# Планирование периодического сохранения данных
def schedule_updates():
    threading.Timer(1800, schedule_updates).start()
    save_user_data()

# Ограничение на отправку жалоб каждые 10 минут
user_report_time = {}

# Проверка, заблокирован ли пользователь
def is_user_banned(user_id):
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None

# Получение юзернейма или ID пользователя
def get_username_or_id(user):
    return f'@{user.username}' if user.username else str(user.id)

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id

    if is_user_banned(user_id):
        cursor = conn.cursor()
        cursor.execute('SELECT admin_id, reason FROM banned_users WHERE user_id = ?', (user_id,))
        admin_id, reason = cursor.fetchone()
        bot.send_message(message.chat.id, f"Вы были заблокированы в данном боте администратором @{admin_id} по причине {reason}\n"
                                          f"Если вы считаете данный бан ошибочным, напишите администратору.")
        return

    cursor = conn.cursor()
    cursor.execute('SELECT first_time FROM referrals WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if not result:
        referrer_id = message.text.split("?start=")[-1] if '?start=' in message.text else None
        cursor.execute('INSERT INTO referrals (user_id, referrer_id, invited_count, first_time, start_time) VALUES (?, ?, 1, 1, ?)', (user_id, referrer_id, datetime.now()))
        conn.commit()

        if referrer_id is not None:
            cursor.execute('UPDATE referrals SET invited_count = invited_count + 1 WHERE user_id = ?', (referrer_id,))
            conn.commit()
    else:
        referrer_id = None

    cursor.execute('UPDATE referrals SET first_time = 0 WHERE user_id = ?', (user_id,))
    conn.commit()

    referral_link = f"https://t.me/{bot.get_me().username}?start={user_id}"

    cursor.execute('SELECT invited_count FROM referrals WHERE user_id = ?', (user_id,))
    invited_count = cursor.fetchone()[0]

    markup = generate_main_menu_markup(user_id)

    bot.send_message(message.chat.id, 
        "Добро пожаловать в MIDEROV SNOS!\n\n"
        "С помощью нашего бота вы сможете отправлять большое количество жалоб на пользователей и их каналы\n"
        "Приобретите подписку по кнопке ниже!",
        reply_markup=markup
    )

# Генерация разметки главного меню
def generate_main_menu_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Купить подписку", callback_data="buy_subscription"),
        types.InlineKeyboardButton("Рефералка", callback_data="referral")
    )
    
    if user_id in ADMIN_IDS:
        markup.row(types.InlineKeyboardButton("Создать промокод", callback_data="create_promocode"))

    cursor = conn.cursor()
    cursor.execute('SELECT end_time FROM user_promotions WHERE user_id = ?', (user_id,))
    promotion = cursor.fetchone()
    if promotion and datetime.strptime(promotion[0], '%Y-%m-%d %H:%M:%S.%f') > datetime.now():
        markup.row(types.InlineKeyboardButton("Снос", callback_data="snos"))
    else:
        markup.row(types.InlineKeyboardButton("Промокод", callback_data="promocode"))

    markup.row(types.InlineKeyboardButton("Оставшееся время", callback_data="remaining_time"))

    return markup

# Обработчик нажатий на кнопки
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id

    if is_user_banned(user_id):
        cursor = conn.cursor()
        cursor.execute('SELECT admin_id, reason FROM banned_users WHERE user_id = ?', (user_id,))
        admin_id, reason = cursor.fetchone()
        bot.send_message(call.message.chat.id, f"Вы были заблокированы в данном боте администратором @{admin_id} по причине {reason}\n"
                                              f"Если вы считаете данный бан ошибочным, напишите администратору.")
        return

    cursor = conn.cursor()

    if call.data == "buy_subscription":
        bot.answer_callback_query(call.id, text="Выберите продолжительность подписки:")

        price_text = ("Прайс данного бота💸\n1 день - 50₽\n1 неделя - 150₽\n1 месяц - 400₽\n1 год - 1000₽\nнавсегда - 3500₽\n Писать по поводу покупки📥 - @liderdoxa\n"
                      "Так же, если вы хотите приобрести сразу много ключей условно под раздачу, то возможен опт🔥"
                     )

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=price_text,
            reply_markup=markup
        )

    elif call.data == "referral":
        referral_link = f"https://t.me/{bot.get_me().username}?start={call.from_user.id}"

        cursor.execute('SELECT invited_count FROM referrals WHERE user_id = ?', (call.from_user.id,))
        
        result = cursor.fetchone()
        invited_count = result[0] if result else 0

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Приглашая по данной ссылке пользователей в бота, вы будете получать 20% времени с купленной ими подписки.\n\n"
                 f"Ваша ссылка: {referral_link}\n\n"
                 f"Количество приглашенных: {invited_count}",
            reply_markup=markup
        )

    elif call.data == "create_promocode":
        if user_id in ADMIN_IDS:
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("2 часа", callback_data="create_promocode_0.08"),
                types.InlineKeyboardButton("1 день", callback_data="create_promocode_1"),
                types.InlineKeyboardButton("1 неделя", callback_data="create_promocode_7"),
                types.InlineKeyboardButton("1 месяц", callback_data="create_promocode_30"),
                types.InlineKeyboardButton("1 год", callback_data="create_promocode_365"),
                types.InlineKeyboardButton("Навсегда", callback_data="create_promocode_forever")
            )
            markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Выберите продолжительность промокода:",
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, text="У вас нет прав для выполнения этой команды")

    elif call.data.startswith("create_promocode_"):
        if user_id in ADMIN_IDS:
            duration_str = call.data.split("_")[2]
            if duration_str == 'forever':
                duration = None
                prefix = "FOREVER-"
            else:
                duration = float(duration_str)
                if duration == 0.08:
                    prefix = "2H-"
                elif duration == 1:
                    prefix = "1D-"
                elif duration == 7:
                    prefix = "1W-"
                elif duration == 30:
                    prefix = "1M-"
                elif duration == 365:
                    prefix = "1Y-"
                else:
                    prefix = ""

            code = generate_promocode(prefix)
            cursor.execute('INSERT INTO promocodes (code, duration) VALUES (?, ?)', (code, duration))
            conn.commit()

            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Создан промокод: `{code}`\nПродолжительность: {'навсегда' if duration is None else f'{int(duration*24)} часов' if duration < 1 else f'{int(duration)} дней'}",
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, text="У вас нет прав для выполнения этой команды")

    elif call.data == "promocode":
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

        msg = bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Введите промокод:",
            reply_markup=markup
        )
        
        bot.register_next_step_handler(msg, process_promocode)

    elif call.data == "snos":
        cursor.execute('SELECT end_time FROM user_promotions WHERE user_id = ?', (user_id,))
        promotion = cursor.fetchone()
        
        if promotion and datetime.strptime(promotion[0], '%Y-%m-%d %H:%M:%S.%f') > datetime.now():
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

            msg = bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Введите текст жалобы✍️:",
                reply_markup=markup
            )

            bot.register_next_step_handler(msg, process_report)
        else:
            bot.answer_callback_query(call.id, text="У вас нет активной подписки")

    elif call.data == "remaining_time":
        cursor.execute('SELECT end_time FROM user_promotions WHERE user_id = ?', (user_id,))
        promotion = cursor.fetchone()

        if promotion:
            remaining_time = datetime.strptime(promotion[0], '%Y-%m-%d %H:%M:%S.%f') - datetime.now()
            days, seconds = remaining_time.days, remaining_time.seconds
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60

            remaining_time_text = f"Оставшееся время подписки: {days} дней, {hours} часов и {minutes} минут"
        else:
            remaining_time_text = "У вас нет активной подписки"

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Назад", callback_data="main_menu"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=remaining_time_text,
            reply_markup=markup
        )

    elif call.data == "main_menu":
        markup = generate_main_menu_markup(user_id)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Вы вернулись в главное меню",
            reply_markup=markup
        )

# Обработчик промокодов
def process_promocode(message):
    user_id = message.from_user.id
    code = message.text.strip().upper()

    cursor = conn.cursor()
    cursor.execute('SELECT duration, used FROM promocodes WHERE code = ?', (code,))
    promocode = cursor.fetchone()

    if promocode:
        duration, used = promocode
        if used:
            bot.send_message(message.chat.id, "Этот промокод уже использован")
        else:
            end_time = datetime.now() + timedelta(days=duration) if duration else None
            cursor.execute('INSERT OR REPLACE INTO user_promotions (user_id, end_time) VALUES (?, ?)', (user_id, end_time))
            cursor.execute('UPDATE promocodes SET used = 1 WHERE code = ?', (code,))
            conn.commit()

            bot.send_message(message.chat.id, f"Промокод успешно активирован! Ваша подписка активна до {end_time}" if end_time else "Промокод успешно активирован! Ваша подписка активна навсегда")
            # Удаление кнопки "Промокод"
            markup = generate_main_menu_markup(user_id)
            bot.send_message(message.chat.id, "Обновленное меню:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Неверный промокод")

# Обработчик жалоб
def process_report(message):
    user_id = message.from_user.id

    if is_user_banned(user_id):
        cursor = conn.cursor()
        cursor.execute('SELECT admin_id, reason FROM banned_users WHERE user_id = ?', (user_id,))
        admin_id, reason = cursor.fetchone()
        bot.send_message(message.chat.id, f"Вы были заблокированы в данном боте администратором @{admin_id} по причине {reason}\n"
                                          f"Если вы считаете данный бан ошибочным, напишите администратору.")
        return

    report_target = message.text.strip()
    current_time = datetime.now()

    if user_id in user_report_time and (current_time - user_report_time[user_id]).total_seconds() < 600:
        bot.send_message(message.chat.id, "Вы можете отправлять жалобы не чаще, чем раз в 10 минут")
        return

    user_report_time[user_id] = current_time

    # Получение username пользователя
    username = message.from_user.username or f"user {user_id}"

    bot.send_message(REPORT_ADMIN_ID, f"Пользователь @{username} отправил жалобу: {report_target}")
    bot.send_message(message.chat.id, "Ваш запрос принят, ожидайте сноса✅")

# Команда /ban
@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            command, identifier, *reason = message.text.split()
            cursor = conn.cursor()
            if identifier.isdigit():
                user_id = int(identifier)
            else:
                user = bot.get_chat(identifier)
                user_id = user.id
            reason = " ".join(reason) if reason else "Не указана"

            cursor.execute('INSERT INTO banned_users (user_id, admin_id, reason) VALUES (?, ?, ?)', (user_id, message.from_user.id, reason))
            conn.commit()

            bot.send_message(message.chat.id, f"Пользователь @{identifier} заблокирован")
        except ValueError:
            bot.send_message(message.chat.id, "Неверный формат команды. Используйте /ban <user_id или @username> <reason>")
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды")

# Команда /unban
@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            command, identifier = message.text.split()
            cursor = conn.cursor()
            if identifier.isdigit():
                user_id = int(identifier)
            else:
                user = bot.get_chat(identifier)
                user_id = user.id

            cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
            conn.commit()

            bot.send_message(message.chat.id, f"Пользователь @{identifier} разблокирован")
        except ValueError:
            bot.send_message(message.chat.id, "Неверный формат команды. Используйте /unban <user_id или @username>")
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды")

@bot.message_handler(commands=['status'])
def user_status(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            command, identifier = message.text.split()
            cursor = conn.cursor()
            
            if identifier.isdigit():
                user_id = int(identifier)
            else:
                user = bot.get_chat(identifier)
                user_id = user.id

            cursor.execute('SELECT reason FROM banned_users WHERE user_id = ?', (user_id,))
            banned = cursor.fetchone()
            
            if banned:
                reason = banned[0]
                status_text = f"Пользователь @{identifier} заблокирован по причине: {reason}"
            else:
                cursor.execute('SELECT end_time FROM user_promotions WHERE user_id = ?', (user_id,))
                promotion = cursor.fetchone()
                
                if promotion:
                    end_time = promotion[0]
                    remaining_time = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S.%f') - datetime.now()
                    days, seconds = remaining_time.days, remaining_time.seconds
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    status_text = f"У пользователя @{identifier} активна подписка. Оставшееся время: {days} дней, {hours} часов и {minutes} минут"
                else:
                    status_text = f"Пользователь @{identifier} не имеет активной подписки и не заблокирован"
            
            bot.send_message(message.chat.id, status_text)
        except ValueError:
            bot.send_message(message.chat.id, "Неверный формат команды. Используйте /status <user_id или @username>")
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды")

# Запуск бота
if __name__ == '__main__':
    bot.polling(none_stop=True)
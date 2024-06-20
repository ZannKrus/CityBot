import re
import telebot
import requests
from os import getenv
from dotenv import load_dotenv
from bs4 import BeautifulSoup as bs
import random
import threading

load_dotenv()
TOKEN = getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# Dictionary to store used cities for each player
player_used_cities = {}
# Dictionary to store game states by room code
games = {}
# Dictionary to store users waiting to enter room codes
waiting_for_room_code = {}
# Possible characters for generating room codes
room_code_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
# Dictionary to track if a player has sent a message during the opponent's turn
message_sent_during_opponent_turn = {}
# Dictionary to store timers
timers = {}

WIKI_URL = "https://ru.wikipedia.org/wiki/%D0%A1%D0%BF%D0%B8%D1%81%D0%BE%D0%BA_%D0%B3%D0%BE%D1%80%D0%BE%D0%B4%D0%BE%D0%B2_%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D0%B8"

# Dictionary to cache city names and their URLs
city_cache = {}


def generate_room_code(length=6):
    return "".join(random.choice(room_code_chars) for _ in range(length))


def load_city_data():
    response = requests.get(WIKI_URL)
    soup = bs(response.content, "html.parser")
    table = soup.find("table", class_="standard sortable")
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        city_name = cells[2].text.strip()
        city_name_cleaned = re.sub(r"\s*\(.*\)|\s*не призн\..*", "", city_name).strip()
        city_url = "https://ru.wikipedia.org" + cells[2].find("a")["href"]
        city_cache[city_name_cleaned.lower()] = city_url


def get_city_info(city_url):
    try:
        response = requests.get(city_url)
        soup = bs(response.text, "html.parser")
        paragraphs = [p.text for p in soup.find_all("p")]
        summary = paragraphs[0] + (paragraphs[1] if len(paragraphs[0]) < 200 else "")
        summary = re.sub(r" \(.*?\)|\[.*?\]|\*\*", "", summary)
        infobox = soup.find("table", {"class": "infobox"})
        population, density, area, mayor, timezone, residents = "", "", "", "", "", ""
        if infobox:
            infobox_text = infobox.text.strip()
            for info in [
                "Население",
                "Плотность",
                "Площадь",
                "Мэр",
                "Часовой пояс",
                "Название жителей",
            ]:
                if info == "Население":
                    match = re.search(
                        r"Население\s+(.*?)\s+(человек|чел.)", infobox_text
                    )
                    if match:
                        population = f"<b>Население:</b> {re.sub(r'\[.*?\]', '', match.group(1).strip())} человек\n"
                else:
                    match = re.search(rf"{info}\s+(.*)\n", infobox_text)
                    if match:
                        value = re.sub(r"[\[\]↗↘]", "", match.group(1).strip())
                        if info == "Плотность":
                            density = f"<b>Плотность населения:</b> {value} \n"
                        elif info == "Площадь":
                            area = f"<b>Площадь:</b> {value} \n"
                        elif info == "Мэр":
                            mayor = f"<b>Мэр:</b> {value}\n"
                        elif info == "Часовой пояс":
                            timezone = f"<b>Часовой пояс:</b> {value}\n"
                        elif info == "Название жителей":
                            residents = f"<b>Название жителей:</b> {value}\n"
        return f"{soup.find('h1').text.strip()}\n\n{summary}\n{population}{density}{area}{mayor}{timezone}{residents}"
    except Exception as e:
        return f"Ошибка при получении информации: {e}"


def find_city_url(city_name):
    return city_cache.get(city_name.lower(), None)


def find_random_city_on_wikipedia(starting_letter, used_cities):
    candidates = [
        (city, url)
        for city, url in city_cache.items()
        if city.startswith(starting_letter.lower()) and city not in used_cities
    ]
    if candidates:
        return random.choice(candidates)
    return None, None


def handle_timeout(room_code):
    game = games.get(room_code)
    if not game:
        return

    current_turn = game["current_turn"]
    opponent_id = (
        game["players"][0] if game["players"][1] == current_turn else game["players"][1]
    )

    game["lives"][current_turn] -= 1
    bot.send_message(
        current_turn,
        f"Время вышло! У вас осталось {game['lives'][current_turn]} жизней. Ход соперника.",
    )
    bot.send_message(
        opponent_id,
        f"Время противника вышло! У него осталось {game['lives'][current_turn]} жизней. Ваш ход.",
    )

    if game["lives"][current_turn] == 0:
        bot.send_message(current_turn, "У вас закончились жизни. Вы проиграли.")
        bot.send_message(opponent_id, "Противник потерял все жизни. Вы победили!")
        del games[room_code]
        return

    game["current_turn"] = opponent_id
    start_timer(room_code)


def start_timer(room_code):
    if room_code in timers:
        timers[room_code].cancel()

    timer = threading.Timer(30.0, handle_timeout, [room_code])
    timers[room_code] = timer
    timer.start()


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "Добро пожаловать в игру в города!\nЧтобы узнать правила игры введите команду /rules.\nЧтобы начать игру, назовите первый город или используйте команды для создания или присоединения к комнате:\n/create_room - создать комнату\n/join_room - присоединиться к комнате",
    )


@bot.message_handler(commands=["rules"])
def send_rules(message):
    bot.send_message(
        message.chat.id,
        "<b>Правила игры в города:</b>\n\n"
        "<b>Цель игры:</b> Называть города не повторяясь. \n\n"
        "<b>Какие города:</b> В игре участвуют только города России.\n\n"
        "<b>Начало игры:</b> Первый игрок называет любой город России.\n\n"
        "<b>Следующий ход:</b> Следующий игрок должен назвать город, который начинается на последнюю букву предыдущего города.\n\n"
        "<b>Игра вдвоём:</b> \n\n"
        "<b>\u2022</b> При игре вдвоем у каждого игрока есть три жизни и 30 секунд на ход. Если игрок не назвал город в течение 30 секунд у него отнимается одна жизнь, а ход переходит сопернику.\n\n"
        "<b>\u2022</b> Во время хода соперника ему можно отправить одно сообщение.\n\n"
        "<b>Исключения:</b> \n\n"
        "<b>\u2022</b> Буквы 'Ъ', 'Ь', 'Ы' не учитываются. Если город заканчивается на одну из этих букв, используется предпоследняя буква.\n\n"
        "<b>\u2022</b> Город можно назвать только один раз за игру.\n\n"
        "<b>Победа:</b> Побеждает тот, кто назовет город, когда у оппонента нет вариантов для продолжения.\n\n"
        "<b>Конец игры:</b> Если вы захотите закончить игру раньше, введите команду /stop.\n\n"
        "<b>Удачи!</b>",
        parse_mode="HTML",
    )


@bot.message_handler(commands=["stop"])
def stop_game(message):
    user_id = message.from_user.id
    room_code = None
    for code, game in games.items():
        if user_id in game["players"]:
            room_code = code
            break

    if room_code:
        game = games.pop(room_code)
        for player_id in game["players"]:
            bot.send_message(
                player_id,
                "Игра окончена. Если хотите начать новую игру, создайте новую комнату или присоединитесь к существующей.",
            )
        del message_sent_during_opponent_turn[game["players"][0]]
        del message_sent_during_opponent_turn[game["players"][1]]
        timers[room_code].cancel()
        del timers[room_code]
    elif user_id in player_used_cities:
        del player_used_cities[user_id]
        bot.send_message(
            message.chat.id,
            "Игра окончена. Если хотите начать новую игру, напишите любой город.",
        )


@bot.message_handler(commands=["create_room"])
def create_room(message):
    room_code = generate_room_code()
    games[room_code] = {
        "players": [message.from_user.id],
        "used_cities": [],
        "last_bot_city": None,
        "current_turn": message.from_user.id,
        "lives": {message.from_user.id: 3},
    }
    message_sent_during_opponent_turn[message.from_user.id] = False
    bot.send_message(
        message.chat.id,
        f"Комната создана! Код комнаты: {room_code}\nДругой игрок может присоединиться, введя команду /join_room и указав код комнаты.",
    )


@bot.message_handler(commands=["join_room"])
def join_room(message):
    user_id = message.from_user.id
    waiting_for_room_code[user_id] = True
    bot.send_message(
        message.chat.id,
        "Введите код комнаты:",
    )


@bot.message_handler(func=lambda message: message.from_user.id in waiting_for_room_code)
def handle_room_code(message):
    user_id = message.from_user.id
    room_code = message.text.strip().upper()
    if room_code in games:
        game = games[room_code]
        if len(game["players"]) < 2:
            game["players"].append(user_id)
            game["lives"][user_id] = 3
            message_sent_during_opponent_turn[game["players"][1]] = False
            bot.send_message(
                message.chat.id,
                f"Вы присоединились к комнате {room_code}. Сейчас ход соперника. У него есть 30 секунд. Дождитесь окончания его хода. ",
            )
            bot.send_message(
                game["players"][0],
                "Другой игрок присоединился к комнате. Сейчас ваш ход. У вас есть 30 секунд. Начните игру, назвав любой город. ",
            )
            start_timer(room_code)
        else:
            bot.send_message(
                message.chat.id,
                f"Комната {room_code} уже заполнена.",
            )
    else:
        bot.send_message(
            message.chat.id,
            f"Комната {room_code} не найдена.",
        )

    del waiting_for_room_code[user_id]


@bot.message_handler(func=lambda message: True)
def play_game(message):
    user_id = message.from_user.id
    room_code = None
    for code, game in games.items():
        if user_id in game["players"]:
            room_code = code
            break

    if not room_code:
        # Singleplayer mode
        if user_id not in player_used_cities:
            player_used_cities[user_id] = {"used_cities": [], "last_bot_city": None}

        used_cities = player_used_cities[user_id]["used_cities"]
        last_bot_city = player_used_cities[user_id]["last_bot_city"]

        user_city = message.text.strip().capitalize()

        if len(user_city) < 2:
            bot.send_message(
                message.chat.id, "Пожалуйста, введите полное название города."
            )
            return

        if user_city in used_cities:
            bot.send_message(
                message.chat.id, f"Город {user_city} уже был назван. Попробуйте другой."
            )
            return

        if last_bot_city:
            last_letter = last_bot_city[-1].upper()
            if last_letter in "ЬЪЫ":
                last_letter = last_bot_city[-2].upper()
            if not user_city.startswith(last_letter):
                bot.send_message(
                    message.chat.id,
                    f"Название города должно начинаться на букву '{last_letter}'. Попробуйте еще раз.",
                )
                return

        city_url = find_city_url(user_city)
        if city_url is None:
            bot.send_message(
                message.chat.id,
                "Я не знаю такого города в России. Попробуйте еще раз.",
            )
            return

        used_cities.append(user_city)
        city_info = get_city_info(city_url)
        bot.send_message(message.chat.id, city_info, parse_mode="HTML")

        last_letter = user_city[-1].upper()
        if last_letter in "ЬЪЫ":
            last_letter = user_city[-2].upper()

        bot_city, bot_city_url = find_random_city_on_wikipedia(last_letter, used_cities)
        if bot_city:
            used_cities.append(bot_city)
            bot_city_info = get_city_info(bot_city_url)
            bot.send_message(message.chat.id, bot_city_info, parse_mode="HTML")
            last_letter = bot_city[-1].upper()
            if last_letter in "ЬЪЫ":
                last_letter = bot_city[-2].upper()
            player_used_cities[user_id]["last_bot_city"] = bot_city
            bot.send_message(
                message.chat.id,
                f"Ваш ход! Назовите город на букву '{last_letter}'",
            )
        else:
            bot.send_message(
                message.chat.id,
                "Поздравляем! Вы выиграли, я не смог найти город на последнюю букву.",
            )
            del player_used_cities[user_id]
            bot.send_message(
                message.chat.id,
                "Игра окончена. Если хотите начать новую игру, напишите любой город.",
            )

    else:
        # Multiplayer mode
        game = games[room_code]
        used_cities = game["used_cities"]
        current_turn = game["current_turn"]

        if user_id != current_turn:
            if not message_sent_during_opponent_turn.get(user_id, False):
                opponent_id = (
                    game["players"][0]
                    if game["players"][1] == user_id
                    else game["players"][1]
                )
                bot.send_message(
                    opponent_id, f"Сообщение от вашего соперника: {message.text}"
                )
                message_sent_during_opponent_turn[user_id] = True
                bot.send_message(
                    message.chat.id, "Ваше сообщение отправлено сопернику."
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "Вы уже отправили сообщение во время хода соперника. Подождите своей очереди.",
                )
            return

        opponent_id = (
            game["players"][0] if game["players"][1] == user_id else game["players"][1]
        )
        message_sent_during_opponent_turn[opponent_id] = False

        user_city = message.text.strip().capitalize()

        if len(user_city) < 2:
            bot.send_message(
                message.chat.id, "Пожалуйста, введите полное название города."
            )
            return

        if user_city in used_cities:
            bot.send_message(
                message.chat.id, f"Город {user_city} уже был назван. Попробуйте другой."
            )
            return

        if used_cities:
            last_city = used_cities[-1]
            last_letter = last_city[-1].upper()
            if last_letter in "ЬЪЫ":
                last_letter = last_city[-2].upper()
            if not user_city.startswith(last_letter):
                bot.send_message(
                    message.chat.id,
                    f"Название города должно начинаться на букву '{last_letter}'. Попробуйте еще раз.",
                )
                return

        city_url = find_city_url(user_city)
        if city_url is None:
            bot.send_message(
                message.chat.id,
                "Я не знаю такого города в России. Попробуйте еще раз.",
            )
            return

        used_cities.append(user_city)
        city_info = get_city_info(city_url)

        bot.send_message(game["players"][0], city_info, parse_mode="HTML")
        bot.send_message(game["players"][1], city_info, parse_mode="HTML")
        game["current_turn"] = opponent_id

        last_letter = user_city[-1].upper()
        if last_letter in "ЬЪЫ":
            last_letter = user_city[-2].upper()

        if game["players"][0] == opponent_id:
            bot.send_message(
                game["players"][0],
                f"Ваш ход! Назовите город на букву '{last_letter}'",
            )
            bot.send_message(
                game["players"][1],
                f"Ход противника на букву '{last_letter}'",
            )
        else:
            bot.send_message(
                game["players"][1],
                f"Ваш ход! Назовите город на букву '{last_letter}'",
            )
            bot.send_message(
                game["players"][0],
                f"Ход противника на букву '{last_letter}'",
            )

        start_timer(room_code)


# Load city data from Wikipedia when the bot starts
load_city_data()

bot.polling()

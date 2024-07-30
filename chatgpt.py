from telebot import telebot, types
from datetime import datetime, timezone, timedelta
import sqlite3
from fpdf import FPDF
import pymysql
import time
from openai import OpenAI
import os
import csv as csvlib

bot = telebot.TeleBot(os.getenv("token"))
branches = {0: "СПБ Парнас", 1: "Ставрополь", 2: "Сургут", 3: "Краснодар", 4: "Тюмень", 5: "Великий Новгород"}   # Словарь id филиалов и названий
users_inputting = {}   # Флаг если пользователь вводит данные
csv_data = []
request_id = 0
sql_verbouse = False

# TODO:
#  обработка excel файла,
#  функции для админов (sql запросы, статистика)
#  таблица для истории запросов
#  сделать логи
#  ? сделать чтобы search() искал все артикулы за одно подключение
#  сделать нормально разделение сообщений
#  кнопка "Отправить заявку"
#  создание файла заявки и отправка по ftp
#  сделать обработку если товар частично в наличии
#  разделение чисел пробелами
#  добавить поиск по всем филиалам
#  amvera


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    global users_inputting, request_id
    chat_id, data = call.data.split(' ', 1)
    if data == "add":
        bot.send_message(chat_id, "Введите свое имя")
        users_inputting[int(chat_id)] = 0
        print(users_inputting)
    if data == "branch":
        bot.send_message(chat_id, "Выберите филиал для поиска и отправьте его цифру:\n1. СПБ Парнас\n2. Ставрополь\n3. Сургут\n4. Краснодар\n5. Тюмень\n6. Великий Новгород")
        users_inputting[int(chat_id)] = 4
    if data == "csv":
        print("CSV DATA : ", csv_data)
        csv_file = csv(csv_data, chat_id, request_id)
        bot.send_document(chat_id, csv_file)
        os.system(f"rm {csv_file.name}")


@bot.message_handler(commands=["start"])
def greet(msg):
    bot.send_message(msg.chat.id, "Напишите заявку, а бот ее обработает")


@bot.message_handler(commands=["sql"])
def sql(msg):
    if sqlite_query(f"SELECT is_admin FROM Users WHERE chat_id = {msg.chat.id}")[0][0] == 0:    # Доступ только у админов
        return
    for i in sqlite_query(msg.text[4:]):
        bot.send_message(msg.chat.id, str(i)+"\n")


@bot.message_handler(commands=["sys"])
def sys(msg):
    if sqlite_query(f"SELECT is_admin FROM Users WHERE chat_id = {msg.chat.id}")[0][0] == 0:    # Доступ только у админов
        return
    res = os.popen(msg.text[4:]).read()
    bot.send_message(msg.chat.id, res if res else "Пустой ответ")


@bot.message_handler(commands=["stat"])
def statistics(msg):
    if sqlite_query(f"SELECT is_admin FROM Users WHERE chat_id = {msg.chat.id}")[0][0] == 0:    # Доступ только у админов
        return
    for i in [i[0] for i in sqlite_query("SELECT DISTINCT article FROM Requests")]:
        bot.send_message(msg.chat.id, i + " - " + str(sqlite_query(f"SELECT SUM(amount) FROM Requests WHERE article = '{i}'")[0][0]))


@bot.message_handler(commands=["settings"])
def settings(msg):
    data = sqlite_query(f"SELECT branch, name, company, phone, email FROM Users WHERE chat_id = {msg.chat.id}")[0]
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="Изменить данные" if data[2] else "Добавить данные", callback_data=str(msg.chat.id)+" add"))
    keyboard.add(types.InlineKeyboardButton(text="Сменить филиал", callback_data=str(msg.chat.id)+" branch"))
    bot.send_message(msg.chat.id, f"""Настройки:\nФилиал: {branches[data[0]]}\nИмя: {data[1] if data[1] else "Не задано"}\nКомпания: {data[2] if data[2] else "Не задано"}\nТелефон: {data[3] if data[3] else "Не задано"}\nEmail: {data[4] if data[4] else "Не задано"}""", reply_markup=keyboard)


# Получение артикула, передача в функцию поиска и обработка
@bot.message_handler(content_types=["text"])
def handle_text(msg):
    global csv_data, request_id
    try:    # Проверка вводит ли пользователь свои данные или заявку
        if users_inputting[msg.chat.id] == 0:
            sqlite_query(f"UPDATE Users SET name = '{msg.text}' WHERE chat_id = '{msg.chat.id}'")
            bot.send_message(msg.chat.id, "Введите свой email")
            users_inputting[msg.chat.id] = 1
            return
        if users_inputting[msg.chat.id] == 1:
            sqlite_query(f"UPDATE Users SET email = '{msg.text}' WHERE chat_id = '{msg.chat.id}'")
            bot.send_message(msg.chat.id, "Введите свой номер телефона")
            users_inputting[msg.chat.id] = 2
            return
        if users_inputting[msg.chat.id] == 2:
            sqlite_query(f"UPDATE Users SET phone = '{msg.text}' WHERE chat_id = '{msg.chat.id}'")
            bot.send_message(msg.chat.id, "Введите название своей компании (напишите 'нет' если нет)")
            users_inputting[msg.chat.id] = 3
            return
        if users_inputting[msg.chat.id] == 3:
            sqlite_query(f"UPDATE Users SET company = '{msg.text}' WHERE chat_id = '{msg.chat.id}'")
            bot.send_message(msg.chat.id, "Вы заполнили личные данные. Теперь вы можете пользоваться ботом без ограничений")
            del users_inputting[msg.chat.id]
            return
        if users_inputting[msg.chat.id] == 4:
            sqlite_query(f"UPDATE Users SET branch = {int(msg.text)-1} WHERE chat_id = '{msg.chat.id}'")
            bot.send_message(msg.chat.id, f"Вы выбрали филиал {branches[int(msg.text)-1]}")
            del users_inputting[msg.chat.id]
            return
    except KeyError:
        pass


    print(msg.text, "    Chat id: ", msg.chat.id)
    if sqlite_query(f"SELECT * FROM Users WHERE chat_id = '{msg.chat.id}'"):    # Если пользователь есть в базе, но не ввел данные и послал больше 3 запросов, отказать
        if not sqlite_query(f"SELECT company FROM Users WHERE chat_id = '{msg.chat.id}'")[0][0] and sqlite_query(f"SELECT requests FROM Users WHERE chat_id = '{msg.chat.id}'")[0][0] >= 3:
            bot.send_message(msg.chat.id, "Пожалйста, добавьте информацию о себе в /settings чтобы продолжить пользоваться ботом")
            return
    else:   # Если пользователя нет в базе, добавить
        sqlite_query(f"INSERT INTO Users (chat_id, requests, branch, is_admin) VALUES ('{msg.chat.id}', 0, 0, 0)")
    placeholder = bot.send_message(msg.chat.id, "Ваш запрос в обработке...", reply_to_message_id=msg.id)
    client = OpenAI(api_key="sk-H3rL4MsruGWYdTIynhMkxfYTaW0HRk5f", base_url="https://api.proxyapi.ru/openai/v1")
    chat = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": "Ты специалист по обработке  заявок от клиентов по расценке автозапчастей. Обычно клиенты присылают список запчастей в виде артикулов (каталожных номеров) и количества которое им нужно. Обычно артикулы состоят из цифр, иногда с добавлением латинских букв. Я буду тебе отправлять заявку от клиента в свободной форме, а ты пришли мне ответ в виде словаря python, где ключ это артикул, а значение - количество. НЕ ПИШИ НИЧЕГО КРОМЕ СЛОВАРЯ. Не пиши ```python. НЕ ПИШИ НИЧЕГО ПЕРЕД СЛОВАРЕМ. ЕСЛИ В ТЕКСТЕ НЕТ АРТИКУЛОВ ВЕРНИ ПУСТОЙ СЛОВАРЬ. Вот примеры артикулов через пробел: 0928400844 0928400821 5301068 0928400689 5257595 16-3501070-110 3302-3502070 231-3502070-20.06 4992135-1 5268413-1 SG1562 3903920 5261257 5261256 5256400 5256400 SB 3900630 PM40004372 3093940 4990385 3913366 3864113 3902116 3914177 3927948 5263944 4891179 3944679 4942710 3901445 3900678 3902460 5290872 3902663 3925402 3913638 4980332 3916361 4934862 PM40004643 3965006 5264231 5261376 3965009 3975389 3954100 5267994 3966430 3966430 3976620 3903309 3907308 4946759 4946759 020003784 4996250 4948504 4946030 4948505 4938949 4938950 3978822 3978824F 3978824 4938942 3945665 5348887 4948508 5340182 4948509 3945918 4955860 3945919 3944158 3945921F 3945921 3916840 3901171 4089804 4892796 3966244 AF25557+AF25558 5313844 g11308 3974163 5284977 3102095 4934063 3949326 5320-3501126 5283368 5267691 4976246 4944137 002-843-057-K 1317304117 3925567 3972687 3972529 4944738 4892320 4892320F 5318121 5272634 4930794 3904166 3900396 3904167 3948095 3948095 3966454 4938632 4936081 4936081 4940656 5307154F 5271866F 3945021 4983047 4943866 4076493F 2872424 2872424F 4921503 5263118 0281002930 4921497 3968437 4921477 3967251 РV10001523 3969395 5344541 5344541F 4931169 0281006102 4921493 4921499 4921495 0281006084 29061SR 29088SR 3967252 РМ40005397 4890189 4326596 2872277 2897342 2897342F 4984760F 2872520 2894872 РМ40005398 4890190 4897224 4088750* 4088832 4954222 РV10001538 4921322 РV10001522 3979176 3979176F 1878001501 1878001501HD 1878006092 1878000206 3482116031 3482125512 3482083118 A21R22.1601090 063082001150 3968886 5260364 3934686 4933502 4933503 3970310 3922072 3004258 3900687 3914035 3901693 3910279 5405579 4944917 3959799 100-3519100 100-3519200-01 100-3519010-01 5285966 5361695 5274915 3938086 3964547 5626388 53404-1112640 3924492 3940735 3940735F 5308264 5261320 5307875 3921444 3940734 5308265 3942589 3933841 4933571 5262906 4930429 1110010013 3979116 3929778 6403179292 29061 29159 29088 3930057 4976170F 4976170 3943888 3943888F 4955169 4955169 3803977 3090450 3080116 4025290 4309423+0.5 4089258 4089258 4089644 3959079 5269330F 5269330 4976251F 3932520 3920691 3920692 5311011F 0634801027 3903475 3090126 3907177 5265277 3936876 5259563 3678606 2898295 4992560F 4992560 PV10002389 3678603 5288373 4058941 3163-1311098-00 4955356 4955357 4090035 4955229 4955229+4955230 4025271+3800558 4089649 4089649+3802376 4025138 5675614 5652872F 4955595 4955591 4089759 4089371 4025069 3801468 3803598 4941224 3968085 3971519 4897115 2872395 2872395 4929865 4931173 3910811 3941927 5271540 5259951 5257978 3910810 3941928 5257979 3926429 11.3537410 4301-3401485 3415603 4980693 3415692 5257996 5262518 3936315 040001691 20005181 PM40004502 4930847 4939896 3930903 PSH0007842 3967762 5294397 4932259 3901895 4895460 4946237 5255310 5269878 5340699 5363383 5264443 5266955 HU6004X 3966589 6402012E 006-B39-22-12V 006-B39-22 020003344 5440-3501105-02/131-02-53 58342-8a503 210577 3925863 5282085 5282085 3960342 3806180 3966841 PM40004188 3800984 5269897 4089909 4948111 3415378 4930793 4938310 5286672 3937027 3948071 4941464 PM40004656 4939586 3971544 5474753 5474752 4937405 3971529 3978022 4987964 3973820 5262500 5398362 3336213 СВ.04519.19.99 5270378 4324101270 4324101027 3966658 5255568 2222821122000 5257057F 3934047 3934046 320402-03-5401212 5270266 5289858 3918800 5266971 5255539 4935915 5287753 5289857 5268212 5289856 5257644 5270241 3943819 3943300 3030770 4898587 6PV 010 033-00 083865850 F53.602.000 Класс 7,5(4) 4897457 3915703 3960495 PM40004227 5302129 5302031 5285962 4946432 3151000079 053151231031 7517 7815 5254972 7611 7613 7608 7610 1307203019 3925878 3922731 4089346 3992118 3926631 PM40004279 4939181 4955337 4955642 4995266F 5264621F 4309425F 5258754 4941395+3966721 4309095 5260019 3915787 3282266 3936993 3947530 3921440 3960324 4983020 4983020F 4983654 PM40004546 3932063 4992913 5266422 2830444 5269779 4946620 4932209 3938267 3415501 3921394 3921393 4932210 4932210 5257187 5257187F 5345648 5345648F 5273045 5273045F 3939353 3944293 5361694 3938156 5266796 5264477F 3935878 3905449 4897569 5255312 5255312F 5263530F 3929011 3918257 3960317 3977913 5262903 5262903F 4990276 4990276 3918174 3977913SET 5262686 3939258 4939246 3938160 4897861 3959052 3911535 4980644F 4899230 5255538 3911941 3901356 3960442 PV10005625 4995186 5348889 PV10002375 3819900 4936080 2170-2902814 3977727 PM40004127 3936365 PT-40-07 PT-40-06 4992135-1R 5266969 5268413R 5256026 3972384 3990774 A875 AVX13-875 4990977 3911588 3289001 3288922 3289897 PM40005154 4991240 3978324 3400884 5254598F 5254599F PM40008431 16-3001020 4947067 4947068 3706-5205800 3802820 3968562 4025270 3920408 3920408F 4890832 4938765 0501218540 5259121 5267091 3966164 4955850 3908830 3940152 3924582 3968074 3927256 3943449 5262813 3933088 3943450 5262173 3927155 4983067 PSH0005945 5263797 5268413 5256026 320402-03-5403040-10 621.3776-01 3901177 4976168 3943198 3940632 4930315 5292708 5257076F 5257076 3928639 3913028 РМ40005673 3931623 4937766 4940179 14.208432-9,6 5367596 3287416 3287418 3926842 5253733 5260415 3415317 3282158 3935821 4983279 4983279F 3415471 5282268 3287430 5255186 4934666 5255187 ППН-45 5255742 4930560 5271464 4934023 3925324 3978244 5284843 3924421 3920595 4933417 5266207 5266593 3918539 3979330 5585632 5343040 3966128 4935040 3930394 4990458 5370734 PSH0008865 4051229 4051323 4039986 3787729 4035100 2834188 3776286 2840685 4045055 4051033 4038209 2881753 1BL 008 193-00 1KO 008 191-027 0631329069 740-1109560 J5700-11132B5 J5700-1107140A 3937743 3401544 PM40004240 LF-16015 53-1012040-10 ZR904X PSH0009180 L111000000366 FF-5485 5283172F 5341.1117075 4324102227 3964003 2ZR 011-172-507 3283576 PM40004126 2830957 5267035 4937065 4988835 4988835 5268408 5347134 5272937 5307809 5272937 4930485 0445120153 3919002 3928031 PM40004144 4937308 5257526 5257526F 3968877. Если количество не указано, то считай, что количество равняется 1 штуке"}, {"role": "user", "content": msg.text}])
    client.close()
    print(chat.choices[0].message.content)
    data = eval(chat.choices[0].message.content)
    if not data:
        bot.send_message(msg.chat.id, "Похоже, вы не ввели артикулы товаров")
        return
    msg_data = []  # Данные для сообщения
    not_found = []  # Не удалось найти
    not_available = []  # Нет в наличии
    pdf_data = []  # Данные для pdf файла
    csv_data = [["Code", "Amount"]]  # Данные для csv файла
    price = 0  # Общая стоимость
    num = 1  # Номер в сообщении
    result = search(data.keys())
    request_id = sqlite_query("SELECT request_id FROM Requests")[-1:][0][0]+1
    print("Result: ", result)
    if result == -1:
        bot.send_message(msg.chat.id, f"Ошибка при выполнении запроса")
        return
    for article_data, article in zip(result, data.keys()):
        sqlite_query(f"INSERT INTO Requests (chat_id, request_id, article, amount) VALUES ('{msg.chat.id}', {request_id}, '{article}', {data[article]})")
        if not article_data:
            # bot.send_message(msg.chat.id, f"Товар по артикулу {article} не найден")
            not_found.append(f"Товар по артикулу {article} не найден")
        else:
            # msg_data.append(f"\nТовары по артикулу {article}:")
            for i in article_data:
                # bot.send_message(msg.chat.id, f"{num + 1}.  {i[10]} {i[0]} - {i[1]} рублей/шт, {data[article]} шт" + (" (нет в наличии)" if i[2] < 1 else ""))
                avaliable = i[2+sqlite_query(f"SELECT branch FROM Users WHERE chat_id = {msg.chat.id}")[0][0]]  # Сколько товаров есть в наличии в выбраном филиале
                if avaliable > 0:  # Вывести и добавить в стоимость только если есть в наличии
                    if avaliable >= data[article]:  # Если в наличии польностью
                        pdf_data.append(f"{num}.  {i[10]} {i[0]} - {i[1]} руб., {data[article]} шт")
                        csv_data.append([str(i[9]), data[article]])
                        msg_data.append(f"{num}.  {i[10]} {i[0]} - {i[1]} руб., {data[article]} шт")
                        price += i[1] * data[article]
                    else:  # Если в наличии не польностью
                        pdf_data.append(f"{num}.  {i[10]} {i[0]} - {i[1]} руб., {avaliable} шт")
                        csv_data.append([str(i[9]), avaliable])
                        msg_data.append(f"{num}.  {i[10]} {i[0]} - {i[1]} руб., {data[article]} шт *(в наличии {avaliable})*")
                        price += i[1] * data[article]
                else:   # Если нет в наличии
                    not_available.append(f"{num}.  {i[10]} {i[0]} - *нет в наличии*")
                num += 1

    msg_data = not_found+["\n"]+not_available+["\n"]+msg_data
    print(msg_data)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="Отправить заявку", callback_data=str(msg.chat.id) + " csv"))
    if pdf_data:
        pdf_data.append(f"Общая стоимость: {price}")
        pdf_file = pdf(pdf_data)
        if len("\n".join(msg_data)) < 4000:
            bot.send_document(msg.chat.id, pdf_file, caption="\n".join(msg_data), reply_to_message_id=msg.id, parse_mode="Markdown", reply_markup=keyboard)
        else:   # Если нельзя отправить целиком, отправить по частям
            bot.send_document(msg.chat.id, pdf_file, reply_to_message_id=msg.id)
            temp = []
            for i in msg_data:
                if sum(map(len, temp)) + len(i) > 4000:
                    bot.send_message(msg.chat.id, "\n".join(temp), parse_mode="Markdown")
                    temp = [i]
                else:
                    temp.append(i)
            if temp:
                bot.send_message(msg.chat.id, "\n".join(temp), parse_mode="Markdown", reply_markup=keyboard)

    elif len(msg_data) > 2:
        if len("\n".join(msg_data)) < 4000:
            bot.send_message(msg.chat.id, "\n".join(msg_data), reply_to_message_id=msg.id, parse_mode="Markdown", reply_markup=keyboard)
        else:   # Если нельзя отправить целиком, отправить по частям
            temp = []
            for i in msg_data:
                if sum(map(len, temp)) + len(i) > 4000:
                    bot.send_message(msg.chat.id, "\n".join(temp), parse_mode="Markdown")
                    temp = [i]
                else:
                    temp.append(i)
            if temp:
                bot.send_message(msg.chat.id, "\n".join(temp), parse_mode="Markdown", reply_markup=keyboard)
    else:
        bot.send_message(msg.chat.id, "Товаров по запросу нет в наличии")
    bot.delete_message(msg.chat.id, placeholder.id)
    sqlite_query(f"UPDATE Users SET requests = requests+1 WHERE chat_id = '{msg.chat.id}'")


def sqlite_query(query):
    if sql_verbouse:
        print(query)
    # logging.info(f"SQL query: {query}")
    con = sqlite3.connect("/data/Camsparts.db")
    cursor = con.cursor()
    result = cursor.execute(query).fetchall()
    if any([i in query for i in ["INSERT", "UPDATE", "DELETE"]]):
        con.commit()
    con.close()
    return result


def pdf(pdf_data):    # Создание pdf файла
    # bot.send_photo(
    #     chat_id,
    #     f"https://spb.camsparts.ru/files/shop_preview/{part[9]}.jpg",
    #     caption=f"{part[0]}\nАртикул: {('*' + part[10] + '*') if select_index == -2 else part[10]}\nКод: {('*' + part[9] + '*') if select_index == -3 else part[9]}\nКросс номера: {part[11][:select_index] + '*' + msg_text.upper() + '*' + part[11][select_index+len(msg_text):] if select_index >= 0 else part[11]}\nЦена розничная: {part[1]}₽\nЦена оптовая: {part[12]}₽\nКоличество:\nСПБ Парнас: {part[2]}, Ставрополь: {part[3]}, Сургут: {part[4]}, Краснодар: {part[5]}, Тюмень: {part[6]}, Великий Новгород: {part[8]}",
    #     parse_mode="Markdown"
    # )
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', 'font/DejaVuSansCondensed.ttf')
    pdf.set_font("DejaVu", size=24)
    html = "<p align='center'>Коммерческое предложение</p><p>" + "</p><p>".join(pdf_data) + "</p>"
    pdf.write_html(html)
    pdf.output("Коммерческое_предложение.pdf")
    return open("Коммерческое_предложение.pdf", "rb")


def csv(csv_data, chat_id, request_id):
    filename = f"{sqlite_query(f"SELECT client_id FROM Users WHERE chat_id = '{chat_id}'")[0][0]}_{request_id}.csv"
    file = open(filename, mode="w", newline="")
    csvlib.writer(file).writerows(csv_data)
    file.close()
    return open(filename, "rb")


# Функция для подключения к базе данных и получения информации
def search(articles):
    try:
        conn = pymysql.connect(
            host=os.environ["host"],
            port=int(os.environ["port"]),
            user=os.environ["user"],
            password=os.environ["password"],
            database=os.environ["database"]
        )

        print("Connected       ", list(articles), "      "+time.ctime())
        # logging.info(
        #     f"User @{msg.from_user.username} "
        #     f"searched {msg.text} "
        #     f"at {str(datetime.now(timezone.utc)+timedelta(hours=3))[:-13]}\n"
        # )
        cursor = conn.cursor()
        data = []   # Данные для возврата
        for article in articles:
            if len(article) == 8 and any([i in article[:1] for i in ["C", "С", "c", "с"]]):
                article = article[1:]
            print("Searching for ", article)
            if not any([k in article for k in ["'", '"', "%", ",", "#", "--", ";"]]):  # Фильтр для избежания SQL инъекции
                cursor.execute(
                    "SELECT name, price, amount_warehouse1, amount_warehouse2, "
                    "amount_warehouse3, amount_warehouse4, amount_warehouse5, "
                    "amount_warehouse7, amount_warehouse6, code, article, text, price2 "
                    f"FROM shop_products WHERE display = 1 AND (article = '{article}' OR text LIKE '%{article}%')"
                )
                data.append(cursor.fetchall())
            else:
                conn.close()
                return -1
        conn.close()
        return data
    except Exception as ex:     # Если ошибка
        print("Error in search: ", ex)
        # logging.error("Exception in search(): ", exc_info=True)
        return -1


# print(sqlite_query("DROP TABLE log"))
# print(sqlite_query("CREATE TABLE log (id INTEGER, username TEXT, request TEXT, exception TEXT, time TEXT, PRIMARY KEY (id))"))
# print(sqlite_query("INSERT INTO users (username, is_admin, settings) VALUES ('SashaKrasikov', 1, '00000')"))
# print(sqlite_query("UPDATE users SET is_admin = 1 WHERE username = 'SashaKrasikov'"))
# print(sqlite_query("SELECT * FROM users"))


bot.infinity_polling()

from flask import Flask, render_template, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackContext
)
import threading
import asyncio
import logging
import xml.dom.minidom
import requests
from datetime import datetime, timedelta
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
import io
import math

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot_thread = None
bot_application = None

SELECTING_ACTION, SELECTING_CURRENCY, ENTERING_CURRENCY, ENTERING_DATE, GRAPH_SELECT_CURRENCY, GRAPH_START_DATE, GRAPH_END_DATE = range(
    7)


def get_all_currencies(date_req=None):
    try:
        if date_req is None:
            date_req = datetime.now().strftime("%d/%m/%Y")
        url = f'https://www.cbr.ru/scripts/XML_daily.asp?date_req={date_req}'
        response = requests.get(url)
        response.raise_for_status()
        dom = xml.dom.minidom.parseString(response.text)
        dom.normalize()
        valutes = dom.getElementsByTagName("Valute")
        currencies = []
        for valute in valutes:
            char_code = valute.getElementsByTagName("CharCode")[0].childNodes[0].nodeValue
            name = valute.getElementsByTagName("Name")[0].childNodes[0].nodeValue
            currencies.append(f"{char_code} - {name}")
        return currencies
    except Exception as e:
        logger.error(f"Error getting currencies: {e}")
        return None


def get_currency_rate(date_req, currency_code):
    try:
        url = f'https://www.cbr.ru/scripts/XML_daily.asp?date_req={date_req}'
        response = requests.get(url)
        response.raise_for_status()
        dom = xml.dom.minidom.parseString(response.text)
        dom.normalize()

        valutes = dom.getElementsByTagName("Valute")
        for valute in valutes:
            char_code = valute.getElementsByTagName("CharCode")[0].childNodes[0].nodeValue
            if char_code == currency_code:
                value = valute.getElementsByTagName("Value")[0].childNodes[0].nodeValue
                nominal = valute.getElementsByTagName("Nominal")[0].childNodes[0].nodeValue
                value = float(value.replace(',', '.')) / float(nominal)
                return round(value, 4)
        return None
    except Exception as e:
        logger.error(f"Error getting currency rate: {e}")
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [KeyboardButton("Выбрать валюту"), KeyboardButton("График")],
        [KeyboardButton("Помощь")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Добро пожаловать в бота курсов валют ЦБ РФ!",
        reply_markup=reply_markup
    )
    return SELECTING_ACTION


async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "Выбрать валюту":
        keyboard = [
            [KeyboardButton("USD"), KeyboardButton("EUR")],
            [KeyboardButton("Выбрать валюту самостоятельно")],
            [KeyboardButton("Назад")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Выберите валюту из списка или введите свою:",
            reply_markup=reply_markup
        )
        return SELECTING_CURRENCY
    elif text == "График":
        context.user_data.clear()
        context.user_data['mode'] = 'graph'
        await update.message.reply_text("Введите код валюты для графика:")
        return GRAPH_SELECT_CURRENCY
    elif text == "Помощь":
        return await help_command(update, context)
    elif text == "Назад":
        return await start(update, context)
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки меню!")
        return SELECTING_ACTION


async def select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "Назад":
        return await start(update, context)
    elif text == "Выбрать валюту самостоятельно":
        currencies = get_all_currencies()
        if currencies:
            message = "Доступные валюты:\n\n" + "\n".join(currencies[:30])
            await update.message.reply_text(message)
            await update.message.reply_text("Введите код валюты:")
            return ENTERING_CURRENCY
        else:
            await update.message.reply_text("Не удалось получить список валют. Попробуйте позже!")
            return SELECTING_CURRENCY
    elif text in ["USD", "EUR"]:
        context.user_data['currency'] = text
        await update.message.reply_text("Введите дату в формате ДД.ММ.ГГГГ:")
        return ENTERING_DATE
    else:
        await update.message.reply_text("Пожалуйста, выберите валюту из предложенных!")
        return SELECTING_CURRENCY


async def graph_select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    currency_code = update.message.text.upper()
    context.user_data['currency'] = currency_code
    await update.message.reply_text("Введите начальную дату в формате ДД.ММ.ГГГГ:")
    return GRAPH_START_DATE


async def process_date_input(date_str: str):
    try:
        day, month, year = map(int, date_str.split('.'))
        if year < 100: year += 2000
        return datetime(year, month, day)
    except:
        raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ")


async def graph_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        input_date = await process_date_input(update.message.text)
        context.user_data['start_date'] = input_date
        await update.message.reply_text("Введите конечную дату в формате ДД.ММ.ГГГГ:")
        return GRAPH_END_DATE
    except Exception as e:
        await update.message.reply_text(f"{str(e)}\nПовторите ввод начальной даты:")
        return GRAPH_START_DATE


async def graph_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        end_date = await process_date_input(update.message.text)
        start_date = context.user_data['start_date']

        if end_date < start_date:
            raise ValueError("Конечная дата должна быть позже начальной")

        total_days = (end_date - start_date).days + 1

        # Адаптивная выборка данных
        if total_days > 365 * 2:  # Более 2 лет - месячные данные
            step = max(30, total_days // 24)  # ~24 точки
            sampling_type = "месячные"
        elif total_days > 180:  # 6 месяцев - 2 года - недельные данные
            step = max(7, total_days // 30)  # ~30 точек
            sampling_type = "недельные"
        elif total_days > 30:  # 1-6 месяцев - 3-дневные данные
            step = max(3, total_days // 30)  # ~30 точек
            sampling_type = "3-дневные"
        else:  # До 1 месяца - ежедневные данные
            step = 1
            sampling_type = "ежедневные"

        dates = []
        rates = []
        current_date = start_date
        counter = 0

        # Собираем данные с адаптивным шагом
        while current_date <= end_date:
            if counter % step == 0:
                formatted_date = current_date.strftime("%d/%m/%Y")
                rate = get_currency_rate(formatted_date, context.user_data['currency'])
                if rate is not None:
                    dates.append(current_date)
                    rates.append(rate)
            current_date += timedelta(days=1)
            counter += 1

        if not dates:
            raise ValueError("Нет данных за указанный период")

        # Настройка графика
        plt.switch_backend('Agg')
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6), facecolor='#121212')
        ax.set_facecolor('#121212')

        # Форматирование осей
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x / 1000:.1f} тыс.' if x >= 1000 else f'{x:.1f}'))

        # Автоматический выбор меток на оси X
        if total_days > 365:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=math.ceil(total_days / 365)))
        elif total_days > 30:
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        else:
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, total_days // 10)))

        # Настройка стиля
        ax.tick_params(axis='both', colors='white', labelsize=8)
        for spine in ax.spines.values():
            spine.set_color('#444444')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')

        # Построение графика
        line_color = '#00ff99'
        if total_days <= 30:  # Для коротких периодов - с точками
            ax.plot(dates, rates, marker='o', linestyle='-', color=line_color,
                    markersize=5, linewidth=1.5, markerfacecolor='#00cc77')
        else:  # Для длинных периодов - только линия
            ax.plot(dates, rates, linestyle='-', color=line_color, linewidth=2)

        # Заголовок и подписи
        ax.set_title(
            f"Курс {context.user_data['currency']} ({sampling_type} данные)\n"
            f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')} ({total_days} дней)",
            pad=20, fontsize=10
        )
        ax.set_xlabel("Дата", labelpad=10)
        ax.set_ylabel("Рубли", labelpad=10)
        ax.grid(color='#333333', linestyle='--', alpha=0.5)

        # Оптимизация расположения
        fig.autofmt_xdate(rotation=45)
        plt.tight_layout(pad=2.0)

        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        plt.close()

        # Отправка графика
        await update.message.reply_photo(
            photo=buf,
            caption=f"Курс {context.user_data['currency']}\n"
                    f"Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
                    f"Данные: {sampling_type}\n"
                    f"Точек на графике: {len(dates)}"
        )
        return await start(update, context)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")
        return await start(update, context)


async def enter_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    currency_code = update.message.text.upper()
    context.user_data['currency'] = currency_code
    await update.message.reply_text("Введите дату в формате ДД.ММ.ГГГГ:")
    return ENTERING_DATE


async def enter_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        input_date = await process_date_input(update.message.text)
        if input_date > datetime.now():
            raise ValueError("Дата не может быть в будущем")

        formatted_date = input_date.strftime("%d/%m/%Y")
        currency_code = context.user_data.get('currency')
        rate = get_currency_rate(formatted_date, currency_code)

        if rate is not None:
            await update.message.reply_text(f"Курс {currency_code} на {input_date.strftime('%d.%m.%Y')}: {rate} руб.")
        else:
            await update.message.reply_text("Данные не найдены")

    except Exception as e:
        await update.message.reply_text(str(e))

    await start(update, context)
    return SELECTING_ACTION


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    help_text = (
        "<b>Помощь по боту курсов валют ЦБ РФ</b>\n\n"
        "<b>Основные функции:</b>\n"
        "1. <b>Выбрать валюту</b> - получить курс на конкретную дату\n"
        "2. <b>График</b> - построить график курса за период\n\n"
        "<b>Формат дат:</b> ДД.ММ.ГГГГ (например, 01.01.2025)\n\n"
        "<b>Особенности графиков:</b>\n"
        "- Для периодов >2 лет используются месячные данные\n"
        "- Для 6 мес-2 лет - недельные данные\n"
        "- Для 1-6 месяцев - 3-дневные данные\n"
        "- Для <1 месяца - ежедневные данные\n\n"
        "Бот автоматически оптимизирует графики для лучшей читаемости."
    )
    await update.message.reply_text(help_text, parse_mode='HTML')
    return SELECTING_ACTION


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Действие отменено!")
    return ConversationHandler.END


async def run_bot(token):
    global bot_application
    try:
        bot_application = Application.builder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                SELECTING_ACTION: [
                    MessageHandler(filters.Regex(r'^(Выбрать валюту|График|Помощь|Назад)$'), select_action),
                ],
                SELECTING_CURRENCY: [
                    MessageHandler(filters.Regex(r'^(USD|EUR|Выбрать валюту самостоятельно|Назад)$'), select_currency),
                ],
                ENTERING_CURRENCY: [MessageHandler(filters.TEXT, enter_currency)],
                ENTERING_DATE: [MessageHandler(filters.TEXT, enter_date)],
                GRAPH_SELECT_CURRENCY: [MessageHandler(filters.TEXT, graph_select_currency)],
                GRAPH_START_DATE: [MessageHandler(filters.TEXT, graph_start_date)],
                GRAPH_END_DATE: [MessageHandler(filters.TEXT, graph_end_date)]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        bot_application.add_handler(conv_handler)
        await bot_application.initialize()
        await bot_application.start()
        await bot_application.updater.start_polling()
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")


def run_async_bot(token):
    asyncio.run(run_bot(token))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start_bot', methods=['POST'])
def start_bot():
    global bot_thread
    token = request.form.get('token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Введите токен'})
    try:
        if bot_thread and bot_thread.is_alive():
            return jsonify({'status': 'error', 'message': 'Бот уже запущен'})
        bot_thread = threading.Thread(target=run_async_bot, args=(token,), daemon=True)
        bot_thread.start()
        return jsonify({'status': 'success', 'message': 'Бот запущен'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
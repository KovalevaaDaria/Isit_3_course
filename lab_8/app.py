from flask import Flask, render_template, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext
)
import threading
import asyncio
import logging
from collections import defaultdict
from datetime import datetime

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = Flask(__name__)
bot_thread = None
bot_application = None
counters = defaultdict(int)
user_data = defaultdict(dict)
last_action = None

button_actions = {
    'Задачи на сегодня', 'Ежедневные привычки', 'Цели на неделю',
    'Добавить задачу', 'Мои задачи', 'Завершить задачу', 'Назад',
    'Домашнее задание', 'Тренировка', 'Рабочая задача',
    'Посмотреть цели', 'Добавить цель', 'Прогресс', 'Редактировать',
    'Трекер воды', 'Физ-активность', 'Чтение', 'Отдых',
    'Выполнено', 'Не выполнено', 'Здоровье', 'Работа', 'Учеба', 'Другое'
}

menus = {
    'main': {
        'text': 'Ваш цифровой планер',
        'keyboard': [
            ['Задачи на сегодня', 'Ежедневные привычки'],
            ['Цели на неделю']
        ]
    },
    'tasks': {
        'text': 'Задачи на сегодня:',
        'keyboard': [
            ['Добавить задачу', 'Мои задачи'],
            ['Завершить задачу', 'Перенести задачу'],
            ['Назад']
        ]
    },
    'habits': {
        'text': 'Ежедневные привычки:',
        'keyboard': [
            ['Трекер воды', 'Физ-активность'],
            ['Чтение', 'Отдых'],
            ['Назад']
        ]
    },
    'goals': {
        'text': 'Цели на неделю:',
        'keyboard': [
            ['Посмотреть цели', 'Добавить цель'],
            ['Прогресс', 'Редактировать'],
            ['Назад']
        ]
    },
    'task_types': {
        'text': 'Выберите тип задачи:',
        'keyboard': [
            ['Домашнее задание', 'Тренировка'],
            ['Рабочая задача', 'Назад']
        ]
    }
}


def get_menu_markup(menu_name):
    menu = menus[menu_name]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(btn) for btn in row] for row in menu['keyboard']],
        resize_keyboard=True,
        input_field_placeholder=menu['text']
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = {
            'state': 'main',
            'water_tracker': {'goal': 1000, 'current': 0},
            'steps_tracker': {'goal': 10000, 'completed': False},
            'reading_tracker': {'goal': 50, 'current': 0},
            'tasks': [],
            'weekly_goals': []
        }
    user_data[user_id]['state'] = 'main'
    await show_menu(update, context, 'main')


async def show_tasks(update: Update, user_id: int):
    tasks = user_data[user_id].get('tasks', [])
    if tasks:
        response = "Список задач:\n\n"
        for i, task in enumerate(tasks, 1):
            response += f"{i}. {task['type']}: {task['description']}\nДата: {task['date']}\n\n"
        await update.message.reply_text(response.strip())
    else:
        await update.message.reply_text("У вас пока нет задач")


async def show_goals(update: Update, user_id: int):
    goals = user_data[user_id].get('weekly_goals', [])
    if goals:
        response = "Ваши цели на неделю:\n\n"
        for i, goal in enumerate(goals, 1):
            response += f"{i}. {goal['title']}\nПрогресс: {goal['progress']}/{goal['target']}\nКатегория: {goal['category']}\n\n"
        await update.message.reply_text(response.strip())
    else:
        await update.message.reply_text("У вас пока нет целей на неделю")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_action
    user_id = update.effective_user.id
    text = update.message.text
    state = user_data[user_id].get('state', 'main')

    if text in button_actions:
        counters[text] += 1
        last_action = text

    try:
        new_state = state

        if text == 'Назад':
            new_state = 'main'
        elif state == 'main':
            new_state = {
                'Задачи на сегодня': 'tasks',
                'Ежедневные привычки': 'habits',
                'Цели на неделю': 'goals'
            }.get(text, state)

        elif state == 'tasks':
            if text == 'Добавить задачу':
                new_state = 'task_types'
            elif text == 'Мои задачи':
                await show_tasks(update, user_id)
                return
            elif text == 'Перенести задачу':
                if user_data[user_id].get('tasks'):
                    await update.message.reply_text(
                        "Введите номер задачи для переноса:",
                        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                    )
                    user_data[user_id]['state'] = 'waiting_task_number_move'
                    return
                else:
                    await update.message.reply_text("Нет задач для переноса")
                    return
            elif text == 'Завершить задачу':
                if user_data[user_id].get('tasks'):
                    await update.message.reply_text(
                        "Введите номер задачи для удаления:",
                        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                    )
                    user_data[user_id]['state'] = 'waiting_task_number_delete'
                    return
                else:
                    await update.message.reply_text("Нет задач для удаления")
                    return
            else:
                new_state = state

        elif state == 'task_types':
            if text in ['Домашнее задание', 'Тренировка', 'Рабочая задача']:
                user_data[user_id]['temp_task'] = {
                    'type': text,
                    'date': datetime.now().strftime("%d.%m.%Y %H:%M")
                }
                await update.message.reply_text(
                    "Введите описание задачи:",
                    reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_description'
                return
            elif text == 'Назад':
                new_state = 'tasks'
            else:
                new_state = state

        elif state == 'waiting_description':
            if text == 'Назад':
                new_state = 'task_types'
            else:
                user_data[user_id]['temp_task']['description'] = text
                user_data[user_id].setdefault('tasks', []).append(user_data[user_id]['temp_task'])
                await update.message.reply_text("Задача успешно добавлена!")
                new_state = 'tasks'
                del user_data[user_id]['temp_task']

        elif state == 'waiting_task_number_delete':
            if text == 'Назад':
                new_state = 'tasks'
            else:
                try:
                    task_num = int(text)
                    tasks = user_data[user_id].get('tasks', [])
                    if 1 <= task_num <= len(tasks):
                        del tasks[task_num - 1]
                        await update.message.reply_text(f"Задача №{task_num} удалена!")
                    else:
                        await update.message.reply_text("Неверный номер задачи")
                    new_state = 'tasks'
                except ValueError:
                    await update.message.reply_text("Введите число")
                    return

        elif state == 'waiting_task_number_move':
            if text == 'Назад':
                new_state = 'tasks'
            else:
                try:
                    task_num = int(text)
                    tasks = user_data[user_id].get('tasks', [])
                    if 1 <= task_num <= len(tasks):
                        user_data[user_id]['move_task_index'] = task_num - 1
                        await update.message.reply_text(
                            "Введите новую дату (ДД.ММ.ГГГГ):",
                            reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                        )
                        user_data[user_id]['state'] = 'waiting_new_date'
                        return
                    else:
                        await update.message.reply_text("Неверный номер задачи")
                        new_state = 'tasks'
                except ValueError:
                    await update.message.reply_text("Введите число")
                    return

        elif state == 'waiting_new_date':
            if text == 'Назад':
                new_state = 'tasks'
            else:
                task_index = user_data[user_id].get('move_task_index')
                user_data[user_id]['tasks'][task_index]['date'] = text
                await update.message.reply_text("Дата задачи обновлена!")
                new_state = 'tasks'

        elif state == 'goals':
            if text == 'Назад':
                new_state = 'main'
            elif text == 'Посмотреть цели':
                await show_goals(update, user_id)
                return
            elif text == 'Добавить цель':
                await update.message.reply_text(
                    "Введите название цели:",
                    reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_goal_title'
                return
            elif text == 'Прогресс':
                if user_data[user_id].get('weekly_goals'):
                    await update.message.reply_text(
                        "Введите номер цели для обновления прогресса:",
                        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                    )
                    user_data[user_id]['state'] = 'waiting_goal_number_progress'
                    return
                else:
                    await update.message.reply_text("У вас пока нет целей")
                    return
            elif text == 'Редактировать':
                if user_data[user_id].get('weekly_goals'):
                    await update.message.reply_text(
                        "Введите номер цели для редактирования:",
                        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                    )
                    user_data[user_id]['state'] = 'waiting_goal_number_edit'
                    return
                else:
                    await update.message.reply_text("У вас пока нет целей")
                    return
            new_state = state

        elif state == 'waiting_goal_title':
            if text == 'Назад':
                new_state = 'goals'
            else:
                user_data[user_id]['temp_goal'] = {'title': text}
                await update.message.reply_text("Введите целевое значение (число):")
                user_data[user_id]['state'] = 'waiting_goal_target'
                return

        elif state == 'waiting_goal_target':
            if text == 'Назад':
                new_state = 'goals'
            else:
                try:
                    target = int(text)
                    user_data[user_id]['temp_goal']['target'] = target
                    user_data[user_id]['temp_goal']['progress'] = 0
                    await update.message.reply_text(
                        "Выберите категорию цели:",
                        reply_markup=ReplyKeyboardMarkup(
                            [['Здоровье', 'Работа'], ['Учеба', 'Другое'], ['Назад']],
                            resize_keyboard=True)
                    )
                    user_data[user_id]['state'] = 'waiting_goal_category'
                    return
                except ValueError:
                    await update.message.reply_text("Пожалуйста, введите число")
                    return

        elif state == 'waiting_goal_category':
            if text == 'Назад':
                new_state = 'goals'
            elif text in ['Здоровье', 'Работа', 'Учеба', 'Другое']:
                user_data[user_id]['temp_goal']['category'] = text
                user_data[user_id].setdefault('weekly_goals', []).append(user_data[user_id]['temp_goal'])
                await update.message.reply_text(
                    "Цель успешно добавлена!",
                    reply_markup=get_menu_markup('goals')
                )
                del user_data[user_id]['temp_goal']
                new_state = 'goals'
            else:
                await update.message.reply_text("Пожалуйста, выберите категорию из предложенных")
                return

        elif state == 'waiting_goal_number_progress':
            if text == 'Назад':
                new_state = 'goals'
            else:
                try:
                    goal_num = int(text)
                    goals = user_data[user_id].get('weekly_goals', [])
                    if 1 <= goal_num <= len(goals):
                        user_data[user_id]['edit_goal_index'] = goal_num - 1
                        await update.message.reply_text(
                            f"Текущий прогресс: {goals[goal_num - 1]['progress']}/{goals[goal_num - 1]['target']}\n"
                            "Введите новое значение прогресса:",
                            reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                        )
                        user_data[user_id]['state'] = 'waiting_goal_progress'
                        return
                    else:
                        await update.message.reply_text("Неверный номер цели")
                        new_state = 'goals'
                except ValueError:
                    await update.message.reply_text("Пожалуйста, введите число")
                    return

        elif state == 'waiting_goal_progress':
            if text == 'Назад':
                new_state = 'goals'
            else:
                try:
                    progress = int(text)
                    goal_index = user_data[user_id]['edit_goal_index']
                    goal = user_data[user_id]['weekly_goals'][goal_index]

                    # Обновляем счетчик прогресса (добавляем введенное значение к текущему)
                    counters['Прогресс'] += progress
                    goal['progress'] += progress

                    if goal['progress'] > goal['target']:
                        goal['progress'] = goal['target']
                        await update.message.reply_text(
                            "Прогресс достиг максимального значения!",
                            reply_markup=get_menu_markup('goals')
                        )
                    else:
                        await update.message.reply_text(
                            "Прогресс обновлен!",
                            reply_markup=get_menu_markup('goals')
                        )
                    new_state = 'goals'
                except ValueError:
                    await update.message.reply_text("Пожалуйста, введите число")
                    return

        elif state == 'waiting_goal_number_edit':
            if text == 'Назад':
                new_state = 'goals'
            else:
                try:
                    goal_num = int(text)
                    goals = user_data[user_id].get('weekly_goals', [])
                    if 1 <= goal_num <= len(goals):
                        user_data[user_id]['edit_goal_index'] = goal_num - 1
                        await update.message.reply_text(
                            "Что вы хотите изменить?",
                            reply_markup=ReplyKeyboardMarkup(
                                [['Название', 'Целевое значение'], ['Категория', 'Удалить'], ['Назад']],
                                resize_keyboard=True)
                        )
                        user_data[user_id]['state'] = 'waiting_goal_edit_choice'
                        return
                    else:
                        await update.message.reply_text("Неверный номер цели")
                        new_state = 'goals'
                except ValueError:
                    await update.message.reply_text("Пожалуйста, введите число")
                    return

        elif state == 'waiting_goal_edit_choice':
            goal_index = user_data[user_id]['edit_goal_index']
            goal = user_data[user_id]['weekly_goals'][goal_index]

            if text == 'Название':
                await update.message.reply_text(
                    f"Текущее название: {goal['title']}\n"
                    "Введите новое название:",
                    reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_goal_new_title'
                return
            elif text == 'Целевое значение':
                await update.message.reply_text(
                    f"Текущее целевое значение: {goal['target']}\n"
                    "Введите новое значение:",
                    reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_goal_new_target'
                return
            elif text == 'Категория':
                await update.message.reply_text(
                    f"Текущая категория: {goal['category']}\n"
                    "Выберите новую категорию:",
                    reply_markup=ReplyKeyboardMarkup(
                        [['Здоровье', 'Работа'], ['Учеба', 'Другое'], ['Назад']],
                        resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_goal_new_category'
                return
            elif text == 'Удалить':
                del user_data[user_id]['weekly_goals'][goal_index]
                await update.message.reply_text(
                    "Цель удалена!",
                    reply_markup=get_menu_markup('goals')
                )
                new_state = 'goals'
            else:
                await update.message.reply_text("Пожалуйста, выберите действие из предложенных")
                return

        elif state == 'waiting_goal_new_title':
            goal_index = user_data[user_id]['edit_goal_index']
            user_data[user_id]['weekly_goals'][goal_index]['title'] = text
            await update.message.reply_text(
                "Название цели обновлено!",
                reply_markup=get_menu_markup('goals')
            )
            new_state = 'goals'

        elif state == 'waiting_goal_new_target':
            try:
                target = int(text)
                goal_index = user_data[user_id]['edit_goal_index']
                user_data[user_id]['weekly_goals'][goal_index]['target'] = target
                await update.message.reply_text(
                    "Целевое значение обновлено!",
                    reply_markup=get_menu_markup('goals')
                )
                new_state = 'goals'
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите число")
                return

        elif state == 'waiting_goal_new_category':
            if text in ['Здоровье', 'Работа', 'Учеба', 'Другое']:
                goal_index = user_data[user_id]['edit_goal_index']
                user_data[user_id]['weekly_goals'][goal_index]['category'] = text
                await update.message.reply_text(
                    "Категория цели обновлена!",
                    reply_markup=get_menu_markup('goals')
                )
                new_state = 'goals'
            else:
                await update.message.reply_text("Пожалуйста, выберите категорию из предложенных")
                return

        elif state == 'habits':
            if text == 'Назад':
                new_state = 'main'
            elif text == 'Трекер воды':
                await handle_water_tracker(update, user_id)
                return
            elif text == 'Физ-активность':
                await handle_activity_tracker(update, user_id)
                return
            elif text == 'Чтение':
                await update.message.reply_text(
                    "Введите количество прочитанных страниц:",
                    reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
                )
                user_data[user_id]['state'] = 'waiting_reading_input'
                return
            elif text == 'Отдых':
                await handle_rest(update, context, user_id)
                return
            else:
                new_state = state

        elif state == 'waiting_reading_input':
            if text == 'Назад':
                new_state = 'habits'
            else:
                try:
                    pages = int(text)
                    tracker = user_data[user_id]['reading_tracker']

                    # Обновляем счетчик чтения (добавляем введенное значение к текущему)
                    counters['Чтение'] += pages
                    tracker['current'] += pages

                    remaining = tracker['goal'] - tracker['current']

                    if remaining > 0:
                        await update.message.reply_text(
                            f"Прочитано {pages} страниц. Всего: {tracker['current']}. Осталось: {remaining}",
                            reply_markup=get_menu_markup('habits')
                        )
                    else:
                        await update.message.reply_text(
                            "Дневная норма чтения выполнена!",
                            reply_markup=get_menu_markup('habits')
                        )
                    new_state = 'habits'
                except ValueError:
                    await update.message.reply_text("Введите число")
                    return

        elif state == 'waiting_activity_confirmation':
            if text in ['Выполнено', 'Не выполнено']:
                await handle_activity_confirmation(update, user_id, text)
                return
            elif text == 'Назад':
                new_state = 'habits'
            else:
                await update.message.reply_text(
                    "Выберите вариант из меню",
                    reply_markup=ReplyKeyboardMarkup([['Выполнено', 'Не выполнено'], ['Назад']], resize_keyboard=True)
                )
                return

        if new_state != state:
            user_data[user_id]['state'] = new_state
            if new_state in menus:
                await show_menu(update, context, new_state)

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text(
            "Произошла ошибка, попробуйте снова",
            reply_markup=get_menu_markup(user_data[user_id].get('state', 'main'))
        )


async def handle_water_tracker(update: Update, user_id: int):
    water_data = user_data[user_id]['water_tracker']
    water_data['current'] += 250
    remaining = max(0, water_data['goal'] - water_data['current'])

    counters['Трекер воды'] += 1

    message = (
        f"Выпито 250 мл воды. Осталось: {remaining} мл"
        if remaining > 0
        else "Норма воды достигнута!"
    )
    await update.message.reply_text(message, reply_markup=get_menu_markup('habits'))


async def handle_activity_tracker(update: Update, user_id: int):
    counters['Физ-активность'] += 1
    await update.message.reply_text(
        "Вы выполнили 10000 шагов сегодня?",
        reply_markup=ReplyKeyboardMarkup(
            [['Выполнено', 'Не выполнено'], ['Назад']],
            resize_keyboard=True
        )
    )
    user_data[user_id]['state'] = 'waiting_activity_confirmation'


async def handle_activity_confirmation(update: Update, user_id: int, choice: str):
    counters[choice] += 1
    user_data[user_id]['steps_tracker']['completed'] = (choice == 'Выполнено')
    response = "Отлично! Так держать!" if choice == 'Выполнено' else "Попробуйте завтра!"
    await update.message.reply_text(response, reply_markup=get_menu_markup('habits'))
    user_data[user_id]['state'] = 'habits'


async def handle_rest(update: Update, context: CallbackContext, user_id: int):
    counters['Отдых'] += 1
    await update.message.reply_text(
        "Отдыхайте 30 секунд...",
        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
    )

    await asyncio.sleep(30)

    if user_data[user_id].get('state') == 'habits':
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Время отдыха закончилось!",
            reply_markup=get_menu_markup('habits')
        )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_name: str):
    await update.message.reply_text(
        text=menus[menu_name]['text'],
        reply_markup=get_menu_markup(menu_name)
    )


async def run_bot(token):
    global bot_application
    try:
        bot_application = Application.builder().token(token).build()
        bot_application.add_handler(CommandHandler("start", start))
        bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        await bot_application.initialize()
        await bot_application.start()
        await bot_application.updater.start_polling()
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"Ошибка запуска бота: {e}")


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


@app.route('/get_stats')
def get_stats():
    global last_action
    filtered_stats = {k: v for k, v in counters.items() if k in button_actions}
    has_data = any(value > 0 for value in filtered_stats.values())
    return jsonify({
        'stats': filtered_stats,
        'last_action': last_action,
        'has_data': has_data
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
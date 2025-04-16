from flask import Flask, render_template, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import threading
import asyncio
import logging
from collections import defaultdict
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
user_data = defaultdict(dict)
counters = defaultdict(int)
last_action = None

# Меню бота
menus = {
    'main': {
        'text': 'Главное меню',
        'keyboard': [
            [InlineKeyboardButton('Задачи', callback_data='tasks'),
             InlineKeyboardButton('Привычки', callback_data='habits')],
            [InlineKeyboardButton('Цели', callback_data='goals'),
             InlineKeyboardButton('Помощь', callback_data='help')]
        ]
    },
    'tasks': {
        'text': 'Управление задачами',
        'keyboard': [
            [InlineKeyboardButton('Добавить задачу', callback_data='add_task'),
             InlineKeyboardButton('Список задач', callback_data='list_tasks')],
            [InlineKeyboardButton('Удалить задачу', callback_data='delete_task'),
             InlineKeyboardButton('Назад', callback_data='back')]
        ]
    },
    'task_categories': {
        'text': 'Выберите категорию:',
        'keyboard': [
            [InlineKeyboardButton('Работа', callback_data='work'),
             InlineKeyboardButton('Учеба', callback_data='study')],
            [InlineKeyboardButton('Личное', callback_data='personal'),
             InlineKeyboardButton('Другое', callback_data='other')],
            [InlineKeyboardButton('Назад', callback_data='back')]
        ]
    },
    'habits': {
        'text': 'Ежедневные привычки',
        'keyboard': [
            [InlineKeyboardButton('Вода', callback_data='water'),
             InlineKeyboardButton('Спорт', callback_data='sport')],
            [InlineKeyboardButton('Чтение', callback_data='reading'),
             InlineKeyboardButton('Отдых', callback_data='rest')],
            [InlineKeyboardButton('Назад', callback_data='back')]
        ]
    },
    'goals': {
        'text': 'Управление целями',
        'keyboard': [
            [InlineKeyboardButton('Добавить цель', callback_data='add_goal'),
             InlineKeyboardButton('Мои цели', callback_data='list_goals')],
            [InlineKeyboardButton('Обновить прогресс', callback_data='update_progress'),
             InlineKeyboardButton('Удалить цель', callback_data='delete_goal')],
            [InlineKeyboardButton('Назад', callback_data='back')]
        ]
    }
}


class BotManager:
    def __init__(self, token):
        self.token = token
        self.application = None
        self.loop = asyncio.new_event_loop()
        self.stop_event = threading.Event()

    async def init_user_data(self, user_id):
        if user_id not in user_data:
            user_data[user_id] = {
                'tasks': [],
                'goals': [],
                'habits': {
                    'water': {'goal': 8, 'current': 0},
                    'sport': {'goal': 1, 'completed': False},
                    'reading': {'goal': 50, 'current': 0},
                    'rest': {'timer': None}
                },
                'last_msg_id': None,
                'state': 'main'
            }

    async def show_menu(self, user_id, menu_name):
        await self.init_user_data(user_id)
        menu = menus[menu_name]
        keyboard = InlineKeyboardMarkup(menu['keyboard'])

        try:
            if user_data[user_id]['last_msg_id']:
                await self.application.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=user_data[user_id]['last_msg_id'],
                    text=menu['text'],
                    reply_markup=keyboard
                )
                return
        except Exception as e:
            logger.error(f"Ошибка редактирования: {e}")

        msg = await self.application.bot.send_message(
            chat_id=user_id,
            text=menu['text'],
            reply_markup=keyboard
        )
        user_data[user_id]['last_msg_id'] = msg.message_id
        user_data[user_id]['state'] = menu_name

    async def start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id
        await self.init_user_data(user_id)
        await self.show_menu(user_id, 'main')

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = query.data
        counters[data] += 1
        global last_action
        last_action = data

        try:
            if data == 'back':
                await self.show_menu(user_id, 'main')
            elif data == 'tasks':
                await self.show_menu(user_id, 'tasks')
            elif data == 'habits':
                await self.show_menu(user_id, 'habits')
            elif data == 'goals':
                await self.show_menu(user_id, 'goals')
            elif data == 'add_task':
                await self.show_menu(user_id, 'task_categories')
            elif data in ['work', 'study', 'personal', 'other']:
                user_data[user_id]['temp_task'] = {'category': data}
                await context.bot.send_message(user_id, "Введите описание задачи:")
                user_data[user_id]['state'] = 'waiting_task_description'
            elif data == 'list_tasks':
                await self.show_tasks(user_id)
            elif data.startswith('delete_task_'):
                index = int(data.split('_')[2])
                await self.delete_task(user_id, index)
            elif data == 'delete_task':
                await self.delete_task_menu(user_id)
            elif data == 'cancel':
                await self.show_menu(user_id, 'tasks')
            elif data == 'water':
                await self.handle_water(user_id)
            elif data == 'sport':
                await self.handle_sport(user_id)
            elif data == 'reading':
                await context.bot.send_message(user_id, "Введите количество страниц:")
                user_data[user_id]['state'] = 'waiting_reading_pages'
            elif data == 'rest':
                await self.handle_rest(user_id)
            elif data == 'add_goal':
                await context.bot.send_message(user_id, "Введите название цели:")
                user_data[user_id]['state'] = 'waiting_goal_title'
            elif data == 'list_goals':
                await self.show_goals(user_id)
            elif data == 'update_progress':
                await self.update_goal_progress_menu(user_id)
            elif data.startswith('update_goal_'):
                index = int(data.split('_')[2])
                user_data[user_id]['temp_goal_index'] = index
                await context.bot.send_message(user_id, "Введите новый прогресс:")
                user_data[user_id]['state'] = 'waiting_goal_progress'
            elif data == 'delete_goal':
                await self.delete_goal_menu(user_id)
            elif data.startswith('delete_goal_'):
                index = int(data.split('_')[2])
                await self.delete_goal(user_id, index)
            elif data == 'help':
                await self.show_help(user_id)
            elif data in ['sport_completed', 'sport_not_completed']:
                await self.handle_sport_confirmation(user_id, data)
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            await context.bot.send_message(user_id, "Ошибка, попробуйте снова")

    async def show_tasks(self, user_id):
        tasks = user_data[user_id].get('tasks', [])
        if not tasks:
            await self.application.bot.send_message(user_id, "Нет задач")
            return

        category_translation = {
            'work': 'Работа',
            'study': 'Учеба',
            'personal': 'Личное',
            'other': 'Другое'
        }

        response = "Ваши задачи:\n\n"
        for i, task in enumerate(tasks, 1):
            translated_category = category_translation.get(task['category'], task['category'])
            response += f"{i}. {translated_category}: {task['description']}\nДата: {task['date']}\n\n"

        await self.application.bot.send_message(user_id, response.strip())

    async def delete_task_menu(self, user_id):
        tasks = user_data[user_id].get('tasks', [])
        if not tasks:
            await self.application.bot.send_message(user_id, "Нет задач для удаления")
            return

        keyboard = [
            [InlineKeyboardButton(f"Удалить задачу {i+1}", callback_data=f"delete_task_{i}")]
            for i, task in enumerate(tasks)
        ]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
        await self.application.bot.send_message(
            user_id,
            "Выберите задачу для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def delete_task(self, user_id, index):
        try:
            tasks = user_data[user_id]['tasks']
            if 0 <= index < len(tasks):
                del tasks[index]
                await self.application.bot.send_message(user_id, "Задача удалена")
                await self.show_menu(user_id, 'tasks')
            else:
                await self.application.bot.send_message(user_id, "Неверный номер")
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await self.application.bot.send_message(user_id, "Ошибка удаления")

    async def handle_water(self, user_id):
        habits = user_data[user_id]['habits']['water']
        habits['current'] += 1
        remaining = habits['goal'] - habits['current']
        message = f"Выпито 250 мл. Осталось: {remaining * 250} мл" if remaining > 0 else "Норма выполнена"
        await self.application.bot.send_message(user_id, message)
        await self.show_menu(user_id, 'habits')

    async def handle_sport(self, user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Выполнено", callback_data="sport_completed"),
             InlineKeyboardButton("Не выполнено", callback_data="sport_not_completed")],
            [InlineKeyboardButton("Назад", callback_data="back")]
        ])
        await self.application.bot.send_message(
            user_id,
            "Вы выполнили 10000 шагов сегодня?",
            reply_markup=keyboard
        )

    async def handle_sport_confirmation(self, user_id, data):
        completed = data == 'sport_completed'
        user_data[user_id]['habits']['sport']['completed'] = completed
        response = "Отлично!" if completed else "Попробуйте завтра"
        await self.application.bot.send_message(user_id, response)
        await self.show_menu(user_id, 'habits')

    async def handle_rest(self, user_id):
        if user_data[user_id]['habits']['rest']['timer']:
            await self.application.bot.send_message(user_id, "Таймер уже активен")
            return

        await self.application.bot.send_message(user_id, "Отдыхайте 30 секунд...")
        user_data[user_id]['habits']['rest']['timer'] = True

        async def rest_timer():
            await asyncio.sleep(30)
            if user_data[user_id]['habits']['rest']['timer']:
                await self.application.bot.send_message(user_id, "Время вышло!")
                user_data[user_id]['habits']['rest']['timer'] = False

        asyncio.create_task(rest_timer())

    async def show_goals(self, user_id):
        goals = user_data[user_id].get('goals', [])
        if not goals:
            await self.application.bot.send_message(user_id, "Нет целей")
            return

        response = "Ваши цели:\n\n"
        for i, goal in enumerate(goals, 1):
            response += f"{i}. {goal['title']} - Прогресс: {goal['progress']}/{goal['target']}\n"
        await self.application.bot.send_message(user_id, response)

    async def update_goal_progress_menu(self, user_id):
        goals = user_data[user_id].get('goals', [])
        if not goals:
            await self.application.bot.send_message(user_id, "Нет целей")
            return

        keyboard = [
            [InlineKeyboardButton(f"Обновить цель {i+1}", callback_data=f"update_goal_{i}")]
            for i, goal in enumerate(goals)
        ]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
        await self.application.bot.send_message(
            user_id,
            "Выберите цель для обновления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def delete_goal_menu(self, user_id):
        goals = user_data[user_id].get('goals', [])
        if not goals:
            await self.application.bot.send_message(user_id, "Нет целей")
            return

        keyboard = [
            [InlineKeyboardButton(f"Удалить цель {i+1}", callback_data=f"delete_goal_{i}")]
            for i, goal in enumerate(goals)
        ]
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
        await self.application.bot.send_message(
            user_id,
            "Выберите цель для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def delete_goal(self, user_id, index):
        try:
            goals = user_data[user_id]['goals']
            if 0 <= index < len(goals):
                del goals[index]
                await self.application.bot.send_message(user_id, "Цель удалена")
                await self.show_menu(user_id, 'goals')
            else:
                await self.application.bot.send_message(user_id, "Неверный номер")
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await self.application.bot.send_message(user_id, "Ошибка удаления")

    async def show_help(self, user_id):
        help_text = (
            "Помощь:\n"
            "1. Задачи - управление задачами\n"
            "2. Привычки - отслеживание активностей\n"
            "3. Цели - работа с целями"
        )
        await self.application.bot.send_message(user_id, help_text)

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        state = user_data[user_id].get('state')

        try:
            # Обработка чтения страниц (добавление к текущему значению)
            if state == 'waiting_reading_pages':
                pages = int(text)
                user_data[user_id]['habits']['reading']['current'] += pages  # Изменено на +=
                await self.application.bot.send_message(
                    user_id,
                    f"Прочитано {pages} страниц. Всего: {user_data[user_id]['habits']['reading']['current']}"
                )
                await self.show_menu(user_id, 'habits')

            # Обработка обновления прогресса целей (добавление к текущему значению)
            elif state == 'waiting_goal_progress':
                index = user_data[user_id]['temp_goal_index']
                progress = int(text)
                user_data[user_id]['goals'][index]['progress'] += progress  # Изменено на +=
                await self.application.bot.send_message(
                    user_id,
                    f"Добавлено {progress}. Текущий прогресс: {user_data[user_id]['goals'][index]['progress']}!"
                )
                await self.show_menu(user_id, 'goals')

            elif state == 'waiting_goal_title':
                user_data[user_id]['temp_goal'] = {'title': text}
                await self.application.bot.send_message(user_id, "Введите целевое значение:")
                user_data[user_id]['state'] = 'waiting_goal_target'

            elif state == 'waiting_goal_target':
                target = int(text)
                user_data[user_id]['temp_goal']['target'] = target
                user_data[user_id]['temp_goal']['progress'] = 0
                user_data[user_id]['goals'].append(user_data[user_id]['temp_goal'])
                del user_data[user_id]['temp_goal']
                await self.show_menu(user_id, 'goals')
                await update.message.reply_text("Цель добавлена!")

            elif state == 'waiting_goal_progress':
                index = user_data[user_id]['temp_goal_index']
                progress = int(text)
                user_data[user_id]['goals'][index]['progress'] = progress
                await self.application.bot.send_message(user_id, "Прогресс обновлен!")
                await self.show_menu(user_id, 'goals')


        except ValueError:
            await update.message.reply_text("Введите число")
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            await self.application.bot.send_message(user_id, "Ошибка обработки данных")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error("Ошибка обработки:", exc_info=context.error)

    async def setup(self):
        self.application = Application.builder().token(self.token).build()
        self.application.add_handler(CommandHandler('start', self.start_handler))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
        self.application.add_error_handler(self.error_handler)
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Бот успешно запущен")

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.setup())
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.application.stop())
        finally:
            self.loop.close()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start_bot', methods=['POST'])
def start_bot():
    token = request.form.get('token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Введите токен'})
    try:
        bot = BotManager(token)
        thread = threading.Thread(target=bot.run)
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'success', 'message': 'Бот запущен'})
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/get_stats')
def get_stats():
    return jsonify({
        'stats': dict(counters),
        'last_action': last_action,
        'has_data': any(counters.values())
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, threaded=True)
from flask import Flask, render_template, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import threading
import asyncio
import logging
import requests
from collections import deque

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = Flask(__name__)
bot_thread = None
bot_application = None
last_messages = deque(maxlen=10)
vk_token = None
tg_token = None


async def send_vk_comment(text: str):
    global vk_token
    try:
        # Получаем user_id владельца токена
        user_info = requests.get(
            'https://api.vk.com/method/users.get',
            params={'access_token': vk_token, 'v': '5.131'}
        ).json()

        if 'error' in user_info:
            logging.error(f"VK Error: {user_info['error']}")
            return False

        user_id = user_info['response'][0]['id']

        # Получаем последний пост
        wall = requests.get(
            'https://api.vk.com/method/wall.get',
            params={
                'owner_id': user_id,
                'count': 1,
                'access_token': vk_token,
                'v': '5.131'
            }
        ).json()

        if 'error' in wall:
            logging.error(f"VK Error: {wall['error']}")
            return False

        post_id = wall['response']['items'][0]['id']

        # Отправляем комментарий
        comment = requests.post(
            'https://api.vk.com/method/wall.createComment',
            params={
                'owner_id': user_id,
                'post_id': post_id,
                'message': text,
                'access_token': vk_token,
                'v': '5.131'
            }
        ).json()

        return 'response' in comment
    except Exception as e:
        logging.error(f"VK Error: {e}")
        return False


async def send_telegram_message(chat_id, text):
    global tg_token
    try:
        bot = Bot(token=tg_token)
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logging.error(f"Telegram send message error: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот активирован!\n\n"
        "Теперь все текстовые сообщения, которые вы присылаете этому боту, "
        "будут автоматически публиковаться как комментарии к последней записи "
        "на вашей стене ВКонтакте.\n\n"
        "Просто отправьте боту текст, который хотите опубликовать."
    )
    last_messages.appendleft({
        'text': 'Бот запущен и готов к работе',
        'status': 'Информация',
        'highlight': True
    })


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    status = 'Успешно' if await send_vk_comment(text) else 'Ошибка'

    # Отправляем подтверждение пользователю
    await send_telegram_message(
        update.message.chat_id,
        f"Ваше сообщение было обработано. Статус: {status}"
    )

    last_messages.appendleft({
        'text': text[:50] + ('...' if len(text) > 50 else ''),
        'status': status,
        'highlight': True
    })


async def run_bot(token):
    global bot_application, tg_token
    tg_token = token
    try:
        application = Application.builder().token(token).build()
        application.add_handler(CommandHandler('start', start_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"Telegram Bot Error: {e}")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start', methods=['POST'])
def start_bot():
    global bot_thread, vk_token
    data = request.get_json()

    if not data.get('tg_token') or not data.get('vk_token'):
        return jsonify({'status': 'error', 'message': 'Необходимы оба токена'})

    if bot_thread and bot_thread.is_alive():
        return jsonify({'status': 'error', 'message': 'Бот уже запущен'})

    try:
        vk_token = data['vk_token']
        bot_thread = threading.Thread(
            target=lambda: asyncio.run(run_bot(data['tg_token'])),
            daemon=True
        )
        bot_thread.start()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/messages')
def get_messages():
    return jsonify({'messages': list(last_messages)[:5]})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
import asyncio
from datetime import datetime, timedelta
import locale
import json
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    ContextTypes, 
    Application, 
    ConversationHandler,
    filters
)
from telegram.error import TimedOut, NetworkError

locale.setlocale(locale.LC_TIME, 'uk_UA.UTF-8')

user_training_start = {}
user_exercises = {}
user_stats = {}

standard_exercises = [
    "Присідання", "Віджимання", "Підтягування", "Планка", 
    "Берпі", "Скручування", "Випади", "Жим штанги лежачи", 
    "Станова тяга",
    ]

def save_data():
    data_to_save = {
        user_id: [
            {
                "date": training["date"],
                "duration": training["duration"],
                "exercises": {
                    exercise: list(sets) for exercise, sets in training["exercises"].items()
                }
            }
            for training in trainings
        ]
        for user_id, trainings in user_stats.items()
    }
    with open('training_data.json', 'w') as f:
        json.dump(data_to_save, f)

def load_data():
    global user_stats
    try:
        with open('training_data.json', 'r') as f:
            user_stats = json.load(f)
    except FileNotFoundError:
        user_stats = {}

load_data()

async def set_commands(application: Application):
    commands = [
        BotCommand("start_training", "Почати тренування"),
        BotCommand("end_training", "Закінчити тренування"),
        BotCommand("choose_exercise", "Обрати вправу"),
        BotCommand("view_stats", "Переглянути статистику"),
    ]
    await application.bot.set_my_commands(commands)

async def start_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    start_time = datetime.now()
    user_training_start[user_id] = start_time
    start_message = f"Тренування розпочато!\nДень: {start_time.strftime('%A')}\nЧас початку: {start_time.strftime('%H:%M:%S')}"
    await update.message.reply_text(start_message)
    await choose_exercise(update, context)

async def end_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_training_start:
        start_time = user_training_start[user_id]
        end_time = datetime.now()
        duration = end_time - start_time
        stats = f"Тренування закінчено!\nДень: {end_time.strftime('%A')}\nЧас закінчення: {end_time.strftime('%H:%M:%S')}\nТривалість: {duration.seconds // 60} хвилин\n\nСтатистика вправ:"
        
        if user_id in user_exercises:
            for exercise, sets in user_exercises[user_id].items():
                stats += f"\n{exercise}: {len(sets)} підходів, {sum(sets)} повторень"
        
        await update.message.reply_text(stats)
        
        # Збереження статистики
        if user_id not in user_stats:
            user_stats[user_id] = []
        user_stats[user_id].append({
            "date": end_time.isoformat(),
            "duration": duration.seconds,
            "exercises": user_exercises.get(user_id, {})
        })
        save_data()
        
        del user_training_start[user_id]
        if user_id in user_exercises:
            del user_exercises[user_id]
    else:
        await update.message.reply_text("Ви ще не починали тренування.")

async def choose_exercise(query_or_update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(query_or_update, Update):
        user_id = query_or_update.effective_user.id
        message_func = query_or_update.message.reply_text
    else:  # CallbackQuery
        user_id = query_or_update.from_user.id
        message_func = query_or_update.edit_message_text
    
    if user_id not in user_exercises:
        user_exercises[user_id] = {}
    
    keyboard = []
    all_exercises = standard_exercises + list(set(user_exercises[user_id].keys()) - set(standard_exercises))
    for exercise in all_exercises:
        keyboard.append([InlineKeyboardButton(exercise, callback_data=f'exercise_{exercise}')])
    
    keyboard.append([InlineKeyboardButton("Додати нову вправу", callback_data='add_exercise')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_func("Виберіть вправу або додайте нову:", reply_markup=reply_markup)

async def choose_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    exercise = context.user_data['current_exercise']
    keyboard = [
        [
            InlineKeyboardButton("5", callback_data=f'reps_5_{exercise}'),
            InlineKeyboardButton("10", callback_data=f'reps_10_{exercise}'),
            InlineKeyboardButton("15", callback_data=f'reps_15_{exercise}'),
            InlineKeyboardButton("20", callback_data=f'reps_20_{exercise}')
        ],
        [InlineKeyboardButton("Ввести іншу кількість", callback_data=f'reps_custom_{exercise}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Виберіть кількість повторень для вправи '{exercise}':", reply_markup=reply_markup)

async def add_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введіть назву нової вправи:")
    return "WAITING_EXERCISE_NAME"

async def handle_new_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_exercise = update.message.text
    if user_id not in user_exercises:
        user_exercises[user_id] = {}
    user_exercises[user_id][new_exercise] = []
    context.user_data['current_exercise'] = new_exercise
    await choose_reps(update, context)
    return "WAITING_REPS"

async def handle_reps_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    reps = data[1]
    exercise = '_'.join(data[2:])  # Об'єднуємо назву вправи, якщо вона містить підкреслення
    
    if reps == 'custom':
        await query.edit_message_text(f"Введіть кількість повторень для вправи '{exercise}':")
        context.user_data['current_exercise'] = exercise
        return "WAITING_CUSTOM_REPS"
    else:
        return await add_reps(query, context, exercise, int(reps))

async def handle_custom_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reps = int(update.message.text)
        exercise = context.user_data['current_exercise']
        return await add_reps(update, context, exercise, reps)
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть коректне число повторень.")
        return "WAITING_CUSTOM_REPS"

async def add_reps(query_or_update, context: ContextTypes.DEFAULT_TYPE, exercise: str, reps: int):
    if isinstance(query_or_update, Update):
        user_id = query_or_update.effective_user.id
        message_func = query_or_update.message.reply_text
    else:  # CallbackQuery
        user_id = query_or_update.from_user.id
        message_func = query_or_update.edit_message_text
    
    if user_id not in user_exercises:
        user_exercises[user_id] = {}
    if exercise not in user_exercises[user_id]:
        user_exercises[user_id][exercise] = []
    
    user_exercises[user_id][exercise].append(reps)
    
    message = f"Додано {reps} повторень до вправи '{exercise}'."
    await message_func(message)
    
    await choose_exercise(query_or_update, context)
    return ConversationHandler.END

async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_stats:
        stats = "Загальна статистика тренувань:\n\n"
        for training in user_stats[user_id]:
            training_date = datetime.fromisoformat(training['date'])
            stats += f"Дата: {training_date.strftime('%d.%m.%Y %H:%M:%S')}\n"
            stats += f"День тижня: {training_date.strftime('%A')}\n"
            stats += f"Тривалість: {training['duration'] // 60} хвилин\n"
            stats += "Вправи:\n"
            for exercise, sets in training['exercises'].items():
                stats += f"  {exercise}: {len(sets)} підходів, {sum(sets)} повторень\n"
            stats += "\n"
        await update.message.reply_text(stats)
    else:
        await update.message.reply_text("У вас ще немає збереженої статистики тренувань.")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'add_exercise':
        await query.message.reply_text("Введіть назву нової вправи:")
        return "WAITING_EXERCISE_NAME"
    elif query.data.startswith('exercise_'):
        exercise = query.data.split('_', 1)[1]
        context.user_data['current_exercise'] = exercise
        return await choose_reps(update, context)
    elif query.data.startswith('reps_'):
        return await handle_reps_choice(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        await asyncio.sleep(1)
        try:
            if update and isinstance(update, Update) and update.message:
                await update.message.reply_text("Виникла тимчасова помилка. Спробуйте ще раз.")
        except Exception as e:
            print(f"Помилка при спробі повідомити користувача: {e}")
    else:
        print(f"Виникла помилка: {context.error}")
        
async def main():
    application = (
        ApplicationBuilder()
        .token("BOT_TOKEN")
        .build()
    )

    application.add_handler(CommandHandler("start_training", start_training))
    application.add_handler(CommandHandler("end_training", end_training))
    application.add_handler(CommandHandler("choose_exercise", choose_exercise))
    application.add_handler(CommandHandler("view_stats", view_stats))

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button), CommandHandler("add_exercise", add_exercise)],
        states={
            "WAITING_EXERCISE_NAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_exercise)],
            "WAITING_REPS": [CallbackQueryHandler(handle_reps_choice)],
            "WAITING_CUSTOM_REPS": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_reps)],
        },
        fallbacks=[],
        per_chat=True,
        per_user=True
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Налаштування команд
    await set_commands(application)

    # Запускаємо бота
    print("Starting bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # Очікуємо сигналу завершення
    stop_signal = asyncio.Future()
    await stop_signal

    # Зупиняємо бота
    await application.stop()

if __name__ == '__main__':
    asyncio.run(main())
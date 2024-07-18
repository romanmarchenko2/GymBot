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

from itertools import groupby
from operator import itemgetter

locale.setlocale(locale.LC_TIME, 'uk_UA.UTF-8')

user_training_start = {}
user_exercises = {}
user_stats = {}
user_meals = {}

standard_exercises = [
    "Присідання", "Віджимання", "Підтягування", "Планка", 
    "Берпі", "Скручування", "Випади", "Жим штанги лежачи", 
    "Станова тяга",
]

def save_data():
    data_to_save = {
        "trainings": {
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
        },
        "meals": user_meals
    }
    with open('user_data.json', 'w') as f:
        json.dump(data_to_save, f)

def load_data():
    global user_stats, user_meals
    try:
        with open('user_data.json', 'r') as f:
            data = json.load(f)
            user_stats = data.get("trainings", {})
            user_meals = data.get("meals", {})
    except FileNotFoundError:
        user_stats = {}
        user_meals = {}

load_data()

async def set_commands(application: Application):
    commands = [
        BotCommand("start_training", "Почати тренування"),
        BotCommand("end_training", "Закінчити тренування"),
        BotCommand("choose_exercise", "Обрати вправу"),
        BotCommand("view_stats", "Переглянути статистику"),
        BotCommand("add_meal", "Додати страву"),
        BotCommand("view_meals", "Переглянути страви"),
    ]
    await application.bot.set_my_commands(commands)

async def start_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    start_time = datetime.now()
    user_training_start[user_id] = start_time
    start_message = f"Тренування розпочато!\nДень: {start_time.strftime('%A')}\nДата та час початку: {start_time.strftime('%d %B %H:%M:%S')}"
    await update.message.reply_text(start_message)
    await choose_exercise(update, context)

async def end_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_training_start:
        start_time = user_training_start[user_id]
        end_time = datetime.now()
        duration = end_time - start_time
        stats = f"Тренування закінчено!\nДень: {end_time.strftime('%A')}\nДата та час закінчення: {end_time.strftime('%d %B %H:%M:%S')}\nТривалість: {duration.seconds // 60} хвилин\n\nСтатистика вправ:"
        
        if user_id in user_exercises:
            for exercise, sets in user_exercises[user_id].items():
                stats += f"\n{exercise}: {len(sets)} підходів, {sum(sets)} повторень"
        
        await update.message.reply_text(stats)
        
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
    exercise = '_'.join(data[2:])
    
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
            stats += f"Дата та час: {training_date.strftime('%d %B %Y %H:%M:%S')}\n"
            stats += f"День тижня: {training_date.strftime('%A')}\n"
            stats += f"Тривалість: {training['duration'] // 60} хвилин\n"
            stats += "Вправи:\n"
            for exercise, sets in training['exercises'].items():
                stats += f"  {exercise}: {len(sets)} підходів, {sum(sets)} повторень\n"
            stats += "\n"
        await update.message.reply_text(stats)
    else:
        await update.message.reply_text("У вас ще немає збереженої статистики тренувань.")

async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введіть назву страви, яку ви з'їли:")
    return "WAITING_MEAL_NAME"

async def handle_new_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    meal_name = update.message.text
    if user_id not in user_meals:
        user_meals[user_id] = []
    user_meals[user_id].append({
        "name": meal_name,
        "date": datetime.now().isoformat()
    })
    save_data()
    await update.message.reply_text(f"Страву '{meal_name}' додано до вашого списку.")
    return ConversationHandler.END

async def view_meals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_meals and user_meals[user_id]:
        # Сортуємо страви за датою
        sorted_meals = sorted(user_meals[user_id], key=lambda x: x['date'])
        
        # Групуємо страви за днем
        grouped_meals = groupby(sorted_meals, key=lambda x: datetime.fromisoformat(x['date']).date())
        
        meals_list = "Ваші страви:\n\n"
        for day, meals in grouped_meals:
            # Форматуємо дату
            day_str = day.strftime('%d %B, %A')
            meals_list += f"День: {day_str}\n"
            
            # Виводимо страви за цей день
            for meal in meals:
                meal_time = datetime.fromisoformat(meal['date']).strftime('%H:%M')
                meals_list += f"   {meal['name']} - Час: {meal_time}\n"
            
            meals_list += "\n"  # Додаємо порожній рядок між днями
        
        await update.message.reply_text(meals_list)
    else:
        await update.message.reply_text("У вас ще немає збережених страв.")

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
    application.add_handler(CommandHandler("view_meals", view_meals))

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button), 
            CommandHandler("add_exercise", add_exercise),
            CommandHandler("add_meal", add_meal)
        ],
        states={
            "WAITING_EXERCISE_NAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_exercise)],
            "WAITING_REPS": [CallbackQueryHandler(handle_reps_choice)],
            "WAITING_CUSTOM_REPS": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_reps)],
            "WAITING_MEAL_NAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_meal)],
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
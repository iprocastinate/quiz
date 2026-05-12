"""
Telegram bot to create and attempt to quizzes.
"""

import logging
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler, filters
import quizbot.bot.create_quiz as createQuiz
import quizbot.bot.attempt_quiz as attemptQuiz
import quizbot.bot.edit_quiz as editQuiz
from quizbot.bot.config import get_config, get_session_factory
from quizbot.bot.persistence import SQLAlchemyPersistence


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update, context):
    """Send a message when the command /start is issued."""
    # Check for deep linking (e.g., /start quiz_123)
    if context.args:
        quiz_query = context.args[0]
        # We redirect to the attempt logic
        return await attemptQuiz.start_from_link(update, context, quiz_query)

    await update.message.reply_text(
        "<b>✨ Welcome to QuizBot! ✨</b>\n\n"
        "I can help you create interactive quizzes exactly like the official one. 🚀\n\n"
        "<b>Quick Commands:</b>\n"
        "➕ /create - Build a new quiz\n"
        "🎯 /attempt - Take an existing quiz\n"
        "✏️ /rename - Change a quiz name\n"
        "🗑️ /remove - Delete a quiz\n"
        "❓ /help - Show all features",
        parse_mode='HTML'
    )


async def print_help(update, _):
    """Send a message when the command /help is issued."""
    help_text = (
        "<b>🛠️ QuizBot Capabilities</b>\n\n"
        "With QuizBot, you can design professional quizzes with various question types: 🧐\n\n"
        "• 🔢 <b>Numbers</b> - Exact or decimal values\n"
        "• 📝 <b>Strings</b> - Text-based answers\n"
        "• ⚖️ <b>Booleans</b> - True/False questions\n"
        "• 🔘 <b>Single Choice</b> - Multiple options, one winner\n"
        "• 🗄️ <b>Multiple Choice</b> - One or more correct answers\n\n"
        "<b>Available Commands:</b>\n"
        "🚀 /create - Start the quiz creation wizard\n"
        "🧠 /attempt - Enter a quiz name to start taking it\n"
        "✍️ /rename - Give one of your quizzes a new name\n"
        "🔥 /remove - Permanently delete a quiz you created\n"
        "🆘 /help - Display this guide\n\n"
        "<i>Enjoy building and testing knowledge! 🥳</i>"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')


async def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def setup_bot(app):
    """Setups the handlers"""

    # Conversation if the user wants to create a quiz
    create_states = {
        'ENTER_NAME': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_quiz_name)],
        'ENTER_DESCRIPTION': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_description)],
        'ENTER_TIMER': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_timer)],
        'ENTER_TYPE': [MessageHandler((filters.TEXT | filters.POLL) & ~filters.COMMAND, createQuiz.enter_type)],
        'ENTER_QUESTION': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_question)],
        'ENTER_ANSWER': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_answer)],
        'ENTER_POSSIBLE_ANSWER': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_possible_answer)],
        'ENTER_RANDOMNESS_QUESTION': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_randomness_question)],
        'ENTER_RANDOMNESS_QUIZ': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_randomness_quiz)],
        'ENTER_RESULT_AFTER_QUESTION': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_result_after_question)],
        'ENTER_RESULT_AFTER_QUIZ': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_result_after_quiz)],
        'ENTER_QUIZ_NAME': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_quiz_name)],
        'ENTER_PASSWORD_CHOICE': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_password_choice)],
        'ENTER_PASSWORD': [MessageHandler(filters.TEXT & ~filters.COMMAND, createQuiz.enter_password)],
    }
    create_handler = ConversationHandler(
        entry_points=[CommandHandler('create', createQuiz.start)],
        states=create_states,
        fallbacks=[CommandHandler('cancelCreate', createQuiz.cancel)],
        name="create_quiz",
        persistent=True,
    )
    app.add_handler(create_handler)

    # Conversation if the user wants to attempt a quiz
    attempt_states = {
        'ENTER_QUIZ': [MessageHandler(filters.TEXT & ~filters.COMMAND, attemptQuiz.enter_quiz)],
        'ENTER_ANSWER': [MessageHandler(filters.TEXT & ~filters.COMMAND, attemptQuiz.enter_answer)],
        'ENTER_PASSWORD': [MessageHandler(filters.TEXT & ~filters.COMMAND, attemptQuiz.enter_password)],
    }
    attempt_handler = ConversationHandler(
        entry_points=[CommandHandler('attempt', attemptQuiz.start)],
        states=attempt_states,
        fallbacks=[CommandHandler('cancelAttempt', attemptQuiz.cancel)],
        name="attempt_quiz",
        persistent=True,
    )
    app.add_handler(attempt_handler)

    # Conversation about remove or renaming exisiting quiz
    edit_states = {
        'ENTER_NAME': [MessageHandler(filters.TEXT & ~filters.COMMAND, editQuiz.enter_name_remove)],
        'ENTER_OLD_NAME': [MessageHandler(filters.TEXT & ~filters.COMMAND, editQuiz.enter_old_name)],
        'ENTER_NEW_NAME': [MessageHandler(filters.TEXT & ~filters.COMMAND, editQuiz.enter_new_name)]
    }
    edit_handler = ConversationHandler(
        entry_points=[CommandHandler('rename', editQuiz.start_rename), CommandHandler(
            'remove', editQuiz.start_remove)],
        states=edit_states,
        fallbacks=[CommandHandler('cancelEdit', editQuiz.cancel_edit)],
        name="edit_quiz",
        persistent=True,
    )
    app.add_handler(edit_handler)

    # Basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", print_help))
    app.add_handler(CommandHandler("quiz", attemptQuiz.start_group_quiz))

    # Button handlers for Group Quiz (Join, Start)
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(attemptQuiz.handle_group_callback))

    # fallback for unrecognized messages
    async def unknown(update, _):
        await update.message.reply_text(
            "I don't understand that. Use /help to see what I can do."
        )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # log all errors
    app.add_error_handler(error)

    # Handle poll answers (for native quiz experience)
    from telegram.ext import PollAnswerHandler
    app.add_handler(PollAnswerHandler(attemptQuiz.receive_quiz_answer))


async def post_init(application):
    """Set bot commands visible in the Telegram command menu."""
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot and see welcome message"),
        BotCommand("help", "Show help and available commands"),
        BotCommand("create", "Create a new quiz (Official-style)"),
        BotCommand("quiz", "Start a group quiz competition"),
        BotCommand("attempt", "Take a quiz privately"),
        BotCommand("rename", "Rename one of your quizzes"),
        BotCommand("remove", "Delete one of your quizzes"),
    ])


if __name__ == '__main__':
    config = get_config()
    Session = get_session_factory(config['DATABASE_URL'])

    persistence = SQLAlchemyPersistence(database_url=config['DATABASE_URL'])
    app = ApplicationBuilder().token(config['TELEGRAM_TOKEN']).persistence(persistence).post_init(post_init).build()
    app.bot_data['Session'] = Session

    setup_bot(app)

    if config['WEBHOOK']:
        app.run_webhook(
            listen="0.0.0.0",
            port=config['PORT'],
            url_path=config['TELEGRAM_TOKEN'],
            webhook_url=config['WEBHOOK'] + config['TELEGRAM_TOKEN'],
        )
    else:
        logger.info('No WEBHOOK set, starting in polling mode')
        app.run_polling()

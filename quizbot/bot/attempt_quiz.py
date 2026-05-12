"""
Module with methods to attempt to a quiz with a telegram bot
"""
import asyncio
import logging
import pickle
import random
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ConversationHandler
from quizbot.quiz.question_factory import QuestionBool, QuestionChoice, \
    QuestionChoiceSingle, QuestionNumber, QuestionString
from quizbot.quiz.attempt import Attempt
from quizbot.bot.models import QuizModel

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update, context):
    """
    Starts a conversation about an attempt at a quiz.
    """
    logger.info('[%s] Attempt initialized', update.message.from_user.username)

    if context.user_data.get('attempt') is not None:
        await update.message.reply_text(
            "<b>⚠️ Quiz in Progress</b>\n\nYou're already taking a quiz! Finish it or /cancelAttempt first.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "<b>🏁 Start a Quiz</b>\n\n"
        "Enter the <b>name</b> of the quiz you want to take.\n"
        "<i>(e.g., 'WorldHistory' or 'WorldHistory john_doe')</i>",
        parse_mode='HTML'
    )
    return 'ENTER_QUIZ'


async def cancel(update, context):
    """Cancels the attempt."""
    context.user_data.clear()
    await update.message.reply_text("<b>❌ Quiz Cancelled.</b>", parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def enter_quiz(update, context):
    """Finds the quiz and prepares for the first question."""
    quizname = update.message.text.split()[0]
    quizcreator = update.message.from_user.username
    if len(update.message.text.split()) > 1:
        quizcreator = update.message.text.split()[1]

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)

    Session = context.bot_data['Session']
    session = Session()
    try:
        result = await asyncio.to_thread(
            session.query(QuizModel).filter_by(username=quizcreator, quizname=quizname).first
        )
    finally:
        session.close()

    if result is None:
        await update.message.reply_text("🔎 <i>Couldn't find that quiz. Try again?</i>", parse_mode='HTML')
        return 'ENTER_QUIZ'

    if result.password is not None and update.message.from_user.username != quizcreator:
        context.user_data['pending_quiz'] = pickle.loads(result.quizinstance)
        context.user_data['pending_password'] = result.password
        context.user_data['pending_quizname'] = quizname
        await update.message.reply_text("<b>🔒 Password Protected</b>\nPlease enter the password to unlock this quiz.", parse_mode='HTML')
        return 'ENTER_PASSWORD'

    return await _init_attempt(update, context, pickle.loads(result.quizinstance), quizname)


async def enter_password(update, context):
    """Verifies password."""
    ph = PasswordHasher()
    try:
        ph.verify(context.user_data['pending_password'], update.message.text)
    except VerifyMismatchError:
        await update.message.reply_text("❌ <b>Wrong password.</b> Try again.", parse_mode='HTML')
        return 'ENTER_PASSWORD'

    quiz = context.user_data['pending_quiz']
    quizname = context.user_data['pending_quizname']
    del context.user_data['pending_quiz'], context.user_data['pending_password'], context.user_data['pending_quizname']
    return await _init_attempt(update, context, quiz, quizname)


async def _init_attempt(update, context, quiz, quizname):
    """Initializes the attempt object and starts the first poll."""
    attempt = Attempt(quiz)
    context.user_data['attempt'] = attempt
    
    await update.message.reply_text(
        "<b>🎯 Quiz: {}</b>\n\n"
        "Total Questions: <b>{}</b>\n"
        "Get ready... the first question is coming! 🚀".format(quizname, attempt.total_questions),
        parse_mode='HTML'
    )
    
    await ask_next_question(update.effective_chat.id, context)
    return 'ENTER_ANSWER'


async def ask_next_question(chat_id, context):
    """Sends the next question as a native Telegram Quiz Poll."""
    attempt = context.user_data['attempt']
    q = attempt.act_question()
    
    # We only support Choice questions for native quizzes
    if not isinstance(q, QuestionChoice):
        # Fallback for text questions (not supported by native polls)
        await context.bot.send_message(chat_id, "<b>[Q{}/{}]</b>\n\n{}".format(attempt.current_index(), attempt.total_questions, q.question), parse_mode='HTML')
        return

    options = q.possible_answers
    # Find correct index
    try:
        correct_index = options.index(q.correct_answer)
    except ValueError:
        correct_index = 0 # Fallback

    message = await context.bot.send_poll(
        chat_id=chat_id,
        question="Question {}/{}: {}".format(attempt.current_index(), attempt.total_questions, q.question),
        options=options,
        type='quiz',
        correct_option_id=correct_index,
        is_anonymous=False,
        explanation="The correct answer is: {}".format(q.correct_answer),
        open_period=attempt.quiz.timer
    )
    
    # Store the poll ID so we know which answer belongs to this attempt
    context.bot_data[message.poll.id] = chat_id


async def start_group_quiz(update, context):
    """Starts the 'Join' phase for a group quiz competition."""
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /quiz [quiz_name]", parse_mode='HTML')
        return

    quiz_name = context.args[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Find the quiz
    Session = context.bot_data['Session']
    session = Session()
    try:
        result = await asyncio.to_thread(session.query(QuizModel).filter_by(quizname=quiz_name).first)
    finally:
        session.close()

    if not result:
        await update.message.reply_text(f"🔎 <i>Couldn't find quiz '{quiz_name}'</i>", parse_mode='HTML')
        return

    # Store group session data
    quiz_data = pickle.loads(result.quizinstance)
    context.chat_data['group_quiz'] = {
        'quiz': quiz_data,
        'quiz_name': quiz_name,
        'players': {}, # user_id -> {name, score}
        'state': 'JOINING',
        'creator_id': update.effective_user.id
    }

    keyboard = [
        [InlineKeyboardButton("➕ Join the Quiz!", callback_data="group_join")],
        [InlineKeyboardButton("🚀 Start Now", callback_data="group_start")]
    ]
    
    await update.message.reply_text(
        "<b>🎮 Group Quiz: {}</b>\n\n"
        "Who is ready to compete? Click <b>Join</b> to enter! 🏁\n\n"
        "<i>Players joined: 0</i>".format(quiz_name),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def handle_group_callback(update, context):
    """Handles buttons for joining and starting the group quiz."""
    query = update.callback_query
    await query.answer()
    
    if 'group_quiz' not in context.chat_data:
        return

    data = context.chat_data['group_quiz']
    user = update.effective_user

    if query.data == "group_join":
        if user.id not in data['players']:
            data['players'][user.id] = {'name': user.first_name, 'score': 0}
            # Update the message with new player count
            keyboard = [
                [InlineKeyboardButton("➕ Join the Quiz!", callback_data="group_join")],
                [InlineKeyboardButton("🚀 Start Now", callback_data="group_start")]
            ]
            await query.edit_message_text(
                "<b>🎮 Group Quiz: {}</b>\n\n"
                "Who is ready to compete? Click <b>Join</b> to enter! 🏁\n\n"
                "<b>Players joined ({}):</b>\n{}".format(
                    data['quiz_name'], 
                    len(data['players']),
                    "\n".join([f"• {p['name']}" for p in data['players'].values()])
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )

    elif query.data == "group_start":
        if user.id != data['creator_id']:
            await query.answer("Only the creator can start the quiz! ✋", show_alert=True)
            return
        
        # Require at least 2 players to make it a competition
        if len(data['players']) < 2:
            await query.answer("Wait for at least 2 players to join! ⏳", show_alert=True)
            return

        data['state'] = 'PLAYING'
        data['attempt'] = Attempt(data['quiz'])
        await query.edit_message_text("<b>🚀 Quiz Starting NOW!</b>\n<i>Everyone in the group can participate!</i>", parse_mode='HTML')
        await ask_group_question(update.effective_chat.id, context)


async def ask_group_question(chat_id, context):
    """Sends a native quiz poll to the group."""
    data = context.chat_data['group_quiz']
    attempt = data['attempt']
    q = attempt.act_question()
    
    if not isinstance(q, QuestionChoice):
        await context.bot.send_message(chat_id, "❌ Error: Group mode only supports Choice questions.")
        return

    options = q.possible_answers
    correct_index = options.index(q.correct_answer)

    message = await context.bot.send_poll(
        chat_id=chat_id,
        question="[Q {}/{}] {}".format(attempt.current_index(), attempt.total_questions, q.question),
        options=options,
        type='quiz',
        correct_option_id=correct_index,
        is_anonymous=False,
        explanation="Correct answer: {}".format(q.correct_answer),
        open_period=data['quiz'].timer
    )
    
    # Track which group this poll belongs to
    context.bot_data[message.poll.id] = {'chat_id': chat_id, 'type': 'GROUP'}


# Update receive_quiz_answer to handle group scoring
async def receive_quiz_answer(update, context):
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    info = context.bot_data.get(poll_id)
    
    if not info: return

    if info.get('type') == 'GROUP':
        chat_id = info['chat_id']
        chat_data = context.application.chat_data.get(chat_id)
        if not chat_data or 'group_quiz' not in chat_data: return
        
        data = chat_data['group_quiz']
        user_id = poll_answer.user.id
        
        # AUTO-JOIN: If user is not in the list, add them automatically
        if user_id not in data['players']:
            data['players'][user_id] = {'name': poll_answer.user.first_name, 'score': 0}
        
        # Check if correct
        attempt = data['attempt']
        q = attempt.act_question()
        is_correct = poll_answer.option_ids[0] == q.possible_answers.index(q.correct_answer)
        
        if is_correct:
            data['players'][user_id]['score'] += 1

        # Logic to move to next question (auto-trigger when timer expires or manual trigger)
        # For now, let's add a manual "Next" trigger or simple auto-logic
        return

    # --- EXISTING PRIVATE QUIZ LOGIC ---
    chat_id = info
    user_id = poll_answer.user.id
    user_data = await context.application.persistence.get_user_data()
    data = user_data.get(user_id)
    if not data or 'attempt' not in data: return
    attempt = data['attempt']
    q = attempt.act_question()
    is_correct = poll_answer.option_ids[0] == q.possible_answers.index(q.correct_answer)
    attempt.user_points.append((is_correct, q))
    attempt.questions.pop(0)
    del context.bot_data[poll_id]
    if attempt.has_next_question():
        await ask_next_question(chat_id, context)
    else:
        score = sum(1 for p, _ in attempt.user_points if p)
        await context.bot.send_message(chat_id, f"<b>🎊 Finished!</b> Score: {score}/{attempt.total_questions}", parse_mode='HTML')
        del data['attempt']
        await context.application.persistence.update_user_data(user_id, data)


async def enter_answer(update, context):
    """Fallback for non-poll messages during quiz."""
    await update.message.reply_text("<i>Please answer the poll above! 👆</i>", parse_mode='HTML')
    return 'ENTER_ANSWER'


async def start_from_link(update, context, quiz_id):
    """Starts a quiz directly from a deep link (ID)."""
    Session = context.bot_data['Session']
    session = Session()
    try:
        # Search by ID instead of name
        result = await asyncio.to_thread(
            session.query(QuizModel).filter_by(id=int(quiz_id)).first
        )
    except (ValueError, TypeError):
        result = None
    finally:
        session.close()

    if result is None:
        await update.message.reply_text("🔎 <i>This quiz link seems to be broken.</i>", parse_mode='HTML')
        return ConversationHandler.END

    quiz = pickle.loads(result.quizinstance)
    
    # If password protected and not creator
    if result.password is not None and update.message.from_user.username != result.username:
        context.user_data['pending_quiz'] = quiz
        context.user_data['pending_password'] = result.password
        context.user_data['pending_quizname'] = result.quizname
        await update.message.reply_text("<b>🔒 Password Protected</b>\nPlease enter the password to unlock this quiz.", parse_mode='HTML')
        # We need to manually set the state for the conversation
        return 'ENTER_PASSWORD'

    return await _init_attempt(update, context, quiz, result.quizname)

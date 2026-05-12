"""
Module with methods to create a quiz with a telegram bot
"""

import asyncio
import logging
import pickle
from argon2 import PasswordHasher
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ConversationHandler
from quizbot.quiz.question_factory import QuestionBool, QuestionChoice,\
    QuestionChoiceSingle, QuestionNumber, QuestionString
from quizbot.quiz.quiz import Quiz
from quizbot.bot.models import QuizModel

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Dict with string and associated question class
dict_question_types = {
    'Ask for a number': QuestionNumber,
    'Ask for a string': QuestionString,
    'Ask for a boolean value': QuestionBool,
    'Ask a multiple choice question': QuestionChoice,
    'Ask a multiple choice question with one correct answer': QuestionChoiceSingle
}


async def start(update, context):
    """Starts the official-style quiz creation flow."""
    if context.user_data.get('quiz') is not None:
        await update.message.reply_text("⚠️ Finish your current creation first or /cancelCreate.")
        return ConversationHandler.END

    context.user_data['quiz_builder'] = {}
    await update.message.reply_text(
        "<b>🆕 New Quiz</b>\n\nLet's create a new quiz! First, give it a <b>Name</b>.",
        parse_mode='HTML'
    )
    return 'ENTER_NAME'


async def enter_quiz_name(update, context):
    """Saves the quiz name and asks for description."""
    context.user_data['quiz_name'] = update.message.text
    await update.message.reply_text(
        "<b>📝 Description</b>\n\nNow, provide a short description for your quiz. ✍️",
        parse_mode='HTML'
    )
    return 'ENTER_DESCRIPTION'


async def enter_description(update, context):
    """Saves description and asks for timer."""
    context.user_data['quiz_description'] = update.message.text
    await update.message.reply_text(
        "<b>⏱️ Time Limit</b>\n\nHow many seconds should users have per question? ⏳",
        reply_markup=ReplyKeyboardMarkup(
            [['10', '15', '30'], ['60', '120', '300']], one_time_keyboard=True
        ),
        parse_mode='HTML'
    )
    return 'ENTER_TIMER'


async def enter_timer(update, context):
    """Initializes the Quiz object with settings and moves to question creation."""
    try:
        timer = int(update.message.text)
    except ValueError:
        timer = 30

    quiz = Quiz(update.message.from_user.username)
    quiz.timer = timer
    # We could store description in the quiz object if we had a field, 
    # for now we just proceed to questions
    context.user_data['quiz'] = quiz
    context.user_data['timer'] = True

    await update.message.reply_text(
        "<b>✨ Great! Now let's add questions.</b>\n\n"
        "Send me a <b>Native Quiz Poll</b> to add it to your quiz, or select a type below.\n\n"
        "<i>When you are finished, press <b>'Enter'</b>.</i>",
        reply_markup=ReplyKeyboardMarkup(
            [[el] for el in list(dict_question_types.keys())] + [['Enter']], 
            one_time_keyboard=True
        ),
        parse_mode='HTML'
    )
    return 'ENTER_TYPE'


async def cancel(update, context):
    """
    Cancels a creation of a quiz by deleting the users' entries.
    """
    logger.info('[%s] Creation canceled by user',
                update.message.from_user.username)

    # Delete user data
    context.user_data.clear()
    await update.message.reply_text(
        "<b>❌ Process Terminated</b>\n\n"
        "I've cleared your current progress. See you next time! 👋",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    return ConversationHandler.END


async def enter_type(update, context):
    """Handles timer setting and poll creation."""
    if 'timer' not in context.user_data:
        try:
            context.user_data['quiz'].timer = int(update.message.text)
            context.user_data['timer'] = True # Mark as set
        except ValueError:
            context.user_data['quiz'].timer = 30 # Fallback
    if update.message.text == "Enter":
        return await enter_randomness_quiz(update, context)

    if update.message.poll:
        poll = update.message.poll
        if poll.type != 'quiz':
            await update.message.reply_text("❌ <b>Error:</b> Please send a <b>Quiz</b> poll (with a correct answer set), not a regular poll.", parse_mode='HTML')
            return 'ENTER_TYPE'
        
        # Extract question data
        q_text = poll.question
        options = [o.text for o in poll.options]
        correct_answer = options[poll.correct_option_id]
        
        from quizbot.quiz.question_factory import QuestionChoiceSingle
        q_instance = QuestionChoiceSingle(q_text, correct_answer)
        q_instance.possible_answers = options
        
        context.user_data['quiz'].add_question(q_instance)
        
        await update.message.reply_text(
            "✅ <b>Question Added!</b>\n\n"
            "Send me another <b>Quiz Poll</b> to add more, or press <b>'Enter'</b> to finish.",
            reply_markup=ReplyKeyboardMarkup([['Enter']], one_time_keyboard=True),
            parse_mode='HTML'
        )
        return 'ENTER_TYPE'

    # Fallback to manual selection if they typed instead of sending poll
    if update.message.text in dict_question_types:
        context.user_data['questtype'] = dict_question_types[update.message.text]
        await update.message.reply_text("<b>📝 Question Text</b>\n\nWhat is the question? 🤔", parse_mode='HTML')
        return 'ENTER_QUESTION'

    await update.message.reply_text(
        "<b>👋 Ready for questions!</b>\n\n"
        "Go ahead and <b>Send me a Quiz Poll</b> (with a correct answer) or select a type below:",
        reply_markup=ReplyKeyboardMarkup(
            [[el] for el in list(dict_question_types.keys())] + [['Enter']], 
            one_time_keyboard=True
        ),
        parse_mode='HTML'
    )
    return 'ENTER_TYPE'


async def enter_question(update, context):
    """
    Asks for the correct answer to the question after entering the question itself.
    """

    # Save question in user_data
    context.user_data['question'] = update.message.text

    logger.info('[%s] Entered new question type "%s"',
                update.message.from_user.username, update.message.text)

    # Ask for correct answer in different ways
    if context.user_data['questtype'] == QuestionChoiceSingle:
        reply_text = "<b>🎯 Correct Answer</b>\n\nPlease enter <b>ONE</b> correct answer ☝️"
    elif context.user_data['questtype'] == QuestionChoice:
        reply_text = "<b>✅ Correct Answers</b>\n\nPlease enter the correct answers separated by <b>', '</b> 🙆‍♂️"
    else:
        reply_text = "<b>✅ Correct Answer</b>\n\nPlease enter the correct answer 🙆‍♂️"

    await update.message.reply_text(reply_text, parse_mode='HTML')
    return 'ENTER_ANSWER'


async def enter_answer(update, context):
    """
    After entering the correct answer it tries to process it.
    If it fails, it asks for the correct answer again.
    Otherwise, it asks for additional possible answers,
    if the question is an instance of QuestionChoice.
    Otherwise, it adds the question to the quiz and asks for the type of the next question.
    """

    # Save correct answer in user_data
    context.user_data['answer'] = update.message.text

    # Try to init question instance
    QuestionType = context.user_data['questtype']
    try:
        context.user_data['questionInstance'] = QuestionType(context.user_data['question'],
                                                              context.user_data['answer'])
    except AssertionError:
        # TODO specify exceptions
        # Error because it isnt a number, no entry, not True/False,...
        await update.message.reply_text(
            "Sorry. Something went wrong by entering your answer. Please try again. 😕")
        logger.info('[%s] Entering correct answer "%s" failed',
                    update.message.from_user.username, update.message.text)
        return 'ENTER_ANSWER'

    logger.info('[%s] Entering correct answer "%s" accepted',
                update.message.from_user.username, update.message.text)

    if isinstance(context.user_data['questionInstance'], QuestionChoice):
        # If QuestionChoice instance, ask for additional possible answers
        await update.message.reply_text(
            "<b>➕ Additional Options</b>\n\n"
            "Please enter additional possible answers separated by <b>', '</b> 😁",
            parse_mode='HTML'
        )
        return 'ENTER_POSSIBLE_ANSWER'

    # Add question to quiz
    context.user_data['quiz'].add_question(
        context.user_data['questionInstance'])

    # Asks for type of next question
    list_question = [[el] for el in list(dict_question_types.keys())]
    await update.message.reply_text(
        "<b>➕ Next Step</b>\n\n"
        "What type of question should the next one be?\n"
        "If you're finished, press <b>'Enter'</b>. 🏁",
        reply_markup=ReplyKeyboardMarkup(
            list_question + [['Enter']], one_time_keyboard=True),
        parse_mode='HTML'
    )
    return 'ENTER_TYPE'


async def enter_possible_answer(update, context):
    """
    After entering additional possible answers, it asks whether the order of the answers
    should be random.
    """

    list_possible_answers = update.message.text.split(', ')
    # Add possible answers to question
    for answer in list_possible_answers:
        context.user_data['questionInstance'].add_possible_answer(answer)

    logger.info('[%s] Entered additional possible answers',
                update.message.from_user.username)

    # Ask for
    await update.message.reply_text(
        "<b>🔀 Answer Randomization</b>\n\n"
        "Should the answers be displayed in random order? 🤔",
        reply_markup=ReplyKeyboardMarkup(
            [['Yes', 'No']], one_time_keyboard=True),
        parse_mode='HTML'
    )

    return 'ENTER_RANDOMNESS_QUESTION'


async def enter_randomness_question(update, context):
    """
    After entering whether the order if the answers should be random,
    it adds the question to the quiz.
    After that, it asks for the type of next question.
    """

    # Check for correct input
    if update.message.text not in ('Yes', 'No'):
        await update.message.reply_text(
            "Thats not a 'Yes' or a 'No' 😕"
            "Should the answers be displayed in random order?",
            reply_markup=ReplyKeyboardMarkup(
                [['Yes', 'No']], one_time_keyboard=True)
        )
        return 'ENTER_RANDOMNESS_QUESTION'

    context.user_data['questionInstance'].is_random = update.message.text == 'Yes'
    logger.info('[%s] Entered randomness of the order of possible answers',
                update.message.from_user.username)

    # Add question to quiz
    context.user_data['quiz'].add_question(
        context.user_data['questionInstance'])
    logger.info('[%s] Added the question to the quiz',
                update.message.from_user.username)

    # Asks for type of next question
    list_question = [[el] for el in list(dict_question_types.keys())]
    await update.message.reply_text(
        "What type of question should the next one be? "
        "If you don't have more questions, press 'Enter'.",
        reply_markup=ReplyKeyboardMarkup(
            list_question + [['Enter']], one_time_keyboard=True)
    )
    return 'ENTER_TYPE'


async def enter_randomness_quiz(update, context):
    """
    After entering whether the order if the questions should be random,
    it asks if the result of the question be displayed after the question itself.
    """

    # Check for correct input
    if update.message.text not in ('Yes', 'No'):
        await update.message.reply_text(
            "Thats not a 'Yes' or a 'No' 😕"
            "Should the questions be displayed in random order?",
            reply_markup=ReplyKeyboardMarkup(
                [['Yes', 'No']], one_time_keyboard=True)
        )
        return 'ENTER_RANDOMNESS_QUIZ'

    # Process input
    context.user_data['quiz'].is_random = update.message.text == 'Yes'

    # Ask for displaying result after question
    await update.message.reply_text(
        "Should the result of the question be displayed after the question?",
        reply_markup=ReplyKeyboardMarkup(
            [['Yes', 'No']], one_time_keyboard=True)
    )

    return 'ENTER_RESULT_AFTER_QUESTION'


async def enter_result_after_question(update, context):
    """
    After entering whether the result of the question should be displayed after the question itself,
    it asks if the result of every question be displayed after the quiz.
    """

    # Check for correct input
    if update.message.text not in ('Yes', 'No'):
        await update.message.reply_text(
            "Thats not a 'Yes' or a 'No' 😕"
            "Should the result of the question be displayed after the question?",
            reply_markup=ReplyKeyboardMarkup(
                [['Yes', 'No']], one_time_keyboard=True)
        )
        return 'ENTER_RESULT_AFTER_QUESTION'

    # Process input
    context.user_data['quiz'].show_results_after_question = update.message.text == 'Yes'

    # Ask for displaying result of every question after quiz
    await update.message.reply_text(
        "Should the result of every question be displayed after the quiz?",
        reply_markup=ReplyKeyboardMarkup(
            [['Yes', 'No']], one_time_keyboard=True)
    )

    return 'ENTER_RESULT_AFTER_QUIZ'


async def enter_result_after_quiz(update, context):
    """
    After entering whether the result of every question should be displayed after the quiz,
    it asks for the name of the quiz?
    """

    # Check for correct input
    if update.message.text not in ('Yes', 'No'):
        await update.message.reply_text(
            "Thats not a 'Yes' or a 'No' 😕"
            "Should the result of every question be displayed after the quiz?",
            reply_markup=ReplyKeyboardMarkup(
                [['Yes', 'No']], one_time_keyboard=True)
        )
        return 'ENTER_RESULT_AFTER_QUIZ'

    # Process input
    context.user_data['quiz'].show_results_after_quiz = update.message.text == 'Yes'

    # Skip password and save directly
    context.user_data['quizname'] = context.user_data.get('quiz_name', 'Untitled Quiz')
    return await _save_quiz(update, context, password=None)


async def enter_quiz_name(update, context):
    """
    After entering the name of the quiz, it looks up if the quiz name is occupied.
    If unique, asks whether the user wants to set a password.
    """

    logger.info('[%s] Completed quiz creation',
                update.message.from_user.username)
    quizname = update.message.text

    # Bot is typing during database query
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)

    # Query for question with input name
    username = update.message.from_user.username
    Session = context.bot_data['Session']
    session = Session()
    try:
        result = await asyncio.to_thread(
            session.query(QuizModel).filter_by(username=username, quizname=quizname).first
        )
    finally:
        session.close()
    if result is not None:
        # Quiz with quizname already exists
        await update.message.reply_text(
            "Sorry. You already have a quiz named {} 😕\nPlease try something else".format(
                quizname)
        )
        logger.info('[%s] Quiz with name "%s" already exists',
                    update.message.from_user.username, update.message.text)

        return 'ENTER_QUIZ_NAME'

    # Store quizname for later save
    context.user_data['quizname'] = quizname

    # Ask if the user wants to set a password
    await update.message.reply_text(
        "<b>🔒 Security Check</b>\n\n"
        "Do you want to set a password for this quiz?\n"
        "<i>Other users will need it to attempt the quiz.</i>",
        reply_markup=ReplyKeyboardMarkup(
            [['Yes', 'No']], one_time_keyboard=True),
        parse_mode='HTML'
    )
    return 'ENTER_PASSWORD_CHOICE'


async def enter_password_choice(update, context):
    """
    After choosing whether to set a password, either asks for the password
    or saves the quiz without one.
    """
    if update.message.text == 'No':
        return await _save_quiz(update, context, password=None)

    if update.message.text == 'Yes':
        await update.message.reply_text("Please enter the password 🔑")
        return 'ENTER_PASSWORD'

    # Invalid input
    await update.message.reply_text(
        "Thats not a 'Yes' or a 'No' 😕"
        "Do you want to set a password for this quiz?",
        reply_markup=ReplyKeyboardMarkup(
            [['Yes', 'No']], one_time_keyboard=True)
    )
    return 'ENTER_PASSWORD_CHOICE'


async def enter_password(update, context):
    """
    Hashes the password and saves the quiz to the database.
    """
    ph = PasswordHasher()
    hashed = ph.hash(update.message.text)
    return await _save_quiz(update, context, password=hashed)


async def _save_quiz(update, context, password=None):
    """
    Saves the quiz to the database with an optional password hash.
    """
    username = update.message.from_user.username
    quizname = context.user_data['quizname']

    Session = context.bot_data['Session']
    session = Session()
    try:
        quiz_row = QuizModel(
            username=username,
            quizname=quizname,
            quizinstance=pickle.dumps(context.user_data['quiz']),
            password=password,
        )
        session.add(quiz_row)
        await asyncio.to_thread(session.commit)
    finally:
        session.close()

    # Get the ID of the new quiz
    session = Session()
    try:
        saved_quiz = session.query(QuizModel).filter_by(username=username, quizname=quizname).first()
        quiz_id = saved_quiz.id
    finally:
        session.close()

    bot_username = (await context.bot.get_me()).username
    share_link = "https://t.me/{}?start={}".format(bot_username, quiz_id)

    await update.message.reply_text(
        "<b>🎉 Quiz Created Successfully!</b>\n\n"
        "You can share your quiz using this link:\n"
        "🔗 {}\n\n"
        "<i>Anyone who clicks this link will start your quiz immediately!</i>".format(share_link),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    logger.info('[%s] Quiz saved as "%s"',
                update.message.from_user.username, quizname)
    # Delete user data
    context.user_data.clear()
    return ConversationHandler.END

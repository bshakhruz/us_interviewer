import os
import tempfile
import logging
from dotenv import load_dotenv
import asyncio
import sys
import difflib

from telegram import Update, File
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from src.agents import (
    prepare_conversation,
    chat,
)

# Configure logging
def setup_logging():
    """Configure logging with appropriate format and levels"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Set up logging to file and console
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/telegram_bot.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Create a logger for this module
    logger = logging.getLogger(__name__)
    return logger

logger = setup_logging()

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not found in environment variables!")
    sys.exit(1)

# Define available commands for suggestion feature
AVAILABLE_COMMANDS = ["start", "new", "help"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"Start command received from User ID: {user_id}, Username: {username}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Здравствуйте! Отправьте мне аудио интервью"
    )

async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"New conversation command received from User ID: {user_id}, Username: {username}")
    
    # Clear any stored conversation state
    context.user_data.clear()
    logger.debug(f"Cleared conversation state for User ID: {user_id}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Новый чат начат. Пожалуйста, отправьте новое аудио интервью."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"Help command received from User ID: {user_id}, Username: {username}")
    
    help_text = """Доступные команды:
/start - Начать разговор с ботом
/new - Начать новый чат (очистить предыдущую историю)
/help - Показать это сообщение с помощью

Для работы сначала отправьте аудиофайл с интервью, затем задавайте вопросы."""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text
    )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands and suggest possible alternatives"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    command = update.message.text.split()[0][1:]  # Remove the '/' prefix
    
    logger.warning(f"Unknown command '{command}' received from User ID: {user_id}, Username: {username}")
    
    # Find closest matching commands
    possible_matches = difflib.get_close_matches(command, AVAILABLE_COMMANDS, n=3, cutoff=0.6)
    
    if possible_matches:
        suggestion_text = f"Неизвестная команда: /{command}. Возможно, вы имели в виду:\n"
        for match in possible_matches:
            suggestion_text += f"/{match}\n"
        suggestion_text += "\nИспользуйте /help для просмотра всех доступных команд."
    else:
        suggestion_text = f"Неизвестная команда: /{command}. Используйте /help для просмотра всех доступных команд."
    
    logger.info(f"Suggesting alternatives for '{command}': {possible_matches}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=suggestion_text
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming audio files, transcribes them, and starts the conversation.
    The audio is saved asynchronously in a user-specific folder and later removed if processed successfully.
    """
    file_path = None
    processed_successfully = False  # flag to decide on file removal
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    logger.info(f"Audio received from User ID: {user_id}, Username: {username}")

    try:
        audio = update.message.audio
        audio_file: File = await audio.get_file()
        
        logger.debug(f"Audio details - File ID: {audio.file_id}, MIME Type: {audio.mime_type}, File Size: {audio.file_size} bytes")

        downloads_dir = os.path.join("downloads", str(user_id))
        os.makedirs(downloads_dir, exist_ok=True)
        logger.debug(f"Created downloads directory: {downloads_dir}")

        mime_type = audio.mime_type
        if mime_type == "audio/mpeg":
            extension = ".mp3"
        elif mime_type == "audio/ogg":
            extension = ".ogg"
        elif mime_type == "audio/mp4":
            extension = ".m4a"
        elif mime_type == "audio/x-m4a":
            extension = ".m4a"
        elif mime_type == "audio/wav":
            extension = ".wav"
        else:
            extension = None
            logger.warning(f"Unsupported audio format: {mime_type} from User ID: {user_id}")

        if extension:
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False, dir=downloads_dir) as temp_file:
                file_path = temp_file.name
            logger.info(f"Downloading audio to temporary file: {file_path}")
            
            download_task = asyncio.create_task(audio_file.download_to_drive(file_path))
            await download_task
            logger.info(f"Audio download completed: {file_path}")
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Неподдерживаемый формат аудио.",
            )
            return

        status_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Аудио получено. Обрабатываю..."
        )

        logger.info(f"Starting conversation preparation with audio file: {file_path}")
        await prepare_conversation(file_path)
        logger.info("Conversation preparation completed successfully")

        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_message.message_id)

        # Check if there is any initial query: either from an audio caption or a text sent earlier
        pending_query = update.message.caption if update.message.caption else context.user_data.get("initial_query")
        if pending_query:
            # If a warning message was sent earlier when text arrived, delete it.
            if context.user_data.get("warning_msg_id"):
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data["warning_msg_id"])
                except Exception as ex:
                    logger.error(f"Could not delete warning message: {str(ex)}")
                context.user_data.pop("warning_msg_id", None)
            context.user_data["initial_query"] = pending_query  # ensure it is stored

            logger.info(f"Processing initial query for User ID: {user_id}: {pending_query[:50]}...")
            query_status = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио обработано. Обрабатываю ваш запрос...",
            )
            try:
                response = await chat(pending_query)
                if response:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query_status.message_id)
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=response,
                        parse_mode="HTML"
                    )
                    processed_successfully = True
                    logger.info(f"Successfully processed initial query for User ID: {user_id}")
            except Exception as e:
                logger.error(f"Error during initial chat for User ID: {user_id}: {str(e)}", exc_info=True)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка при обработке вашего запроса.",
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио обработано. Можете задавать вопросы.",
            )
            processed_successfully = True

        context.user_data["chatting"] = True
        # Clean up the stored initial query
        context.user_data.pop("initial_query", None)

    except Exception as e:
        logger.error(f"Error processing audio for User ID: {user_id}: {str(e)}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при обработке аудио.",
        )
    finally:
        if processed_successfully and file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Removed temporary file: {file_path}")
            except Exception as remove_error:
                logger.error(f"Failed to remove temporary file {file_path}: {str(remove_error)}", exc_info=True)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages (user queries) if the bot is in chat mode."""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    user_query = update.message.text
    
    if context.user_data.get("chatting"):
        logger.info(f"Processing text query from User ID: {user_id}, Username: {username}: {user_query[:50]}...")
    
        processing_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Обрабатываю ваш запрос..."
        )
        try:
            response = await chat(user_query)
            if response:
                logger.debug(f"Response generated for User ID: {user_id}, Response length: {len(response)}")
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_msg.message_id)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=response,
                    parse_mode="HTML"
                )
                logger.info(f"Response sent to User ID: {user_id}")
        except Exception as e:
            logger.error(f"Error during chat for User ID: {user_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке вашего запроса.",
            )
    else:
        logger.warning(f"User ID: {user_id} attempted to send a query before audio was received")
        # Save the text query to be processed later when audio is received.
        if "initial_query" not in context.user_data:
            context.user_data["initial_query"] = user_query
            warning_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио ещё не получено. Ваш запрос сохранён и будет обработан после получения аудио."
            )
            context.user_data["warning_msg_id"] = warning_msg.message_id
        else:
            # Append subsequent texts (if needed)
            context.user_data["initial_query"] += "\n" + user_query
            if "warning_msg_id" in context.user_data:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data["warning_msg_id"],
                        text="Аудио ещё не получено. Ваш запрос сохранён и будет обработан после получения аудио."
                    )
                except Exception as e:
                    logger.error(f"Failed to edit warning message: {str(e)}", exc_info=True)



def main():
    logger.info("Starting Telegram bot application")
    try:
        application = ApplicationBuilder().token(TOKEN).build()

        # Register command handlers
        start_handler = CommandHandler("start", start)
        new_handler = CommandHandler("new", new)
        help_handler = CommandHandler("help", help_command)
        
        # Register message handlers
        audio_handler = MessageHandler(filters.AUDIO, handle_audio)
        text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
        
        # Handler for unknown commands - must be added last
        unknown_handler = MessageHandler(filters.COMMAND, unknown_command)

        application.add_handler(start_handler)
        application.add_handler(new_handler)
        application.add_handler(help_handler)
        application.add_handler(audio_handler)
        application.add_handler(text_handler)
        application.add_handler(unknown_handler)  # Must be added last

        logger.info("Handlers registered, starting polling...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Failed to start the bot: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
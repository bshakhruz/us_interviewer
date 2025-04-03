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
    transcribe_voice,
    chat,
)

def setup_logging():
    """Configure structured logging with file and console output"""
    os.makedirs("logs", exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/telegram_bot.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

logger = setup_logging()
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not found in environment variables!")
    sys.exit(1)

# Command registry for suggestion feature
AVAILABLE_COMMANDS = ["start", "new", "help"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initial greeting and instructions"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"Start command received from User ID: {user_id}, Username: {username}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Здравствуйте! Отправьте мне аудио интервью"
    )

async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset conversation state"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"New conversation command received from User ID: {user_id}, Username: {username}")
    
    context.user_data.clear()
    logger.debug(f"Cleared conversation state for User ID: {user_id}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Новый чат начат. Пожалуйста, отправьте новое аудио интервью."
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display available commands and usage instructions"""
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
    """Handle unknown commands with fuzzy matching for suggestions"""
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler for graceful failure recovery"""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(context.error, Exception) and "httpx.ReadError" in str(context.error):
        logger.warning("A network read error occurred. It may be due to a bad connection.")

    # Only notify user if we can determine the chat
    if update and getattr(update, "effective_chat", None):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла временная ошибка в сети. Пожалуйста, попробуйте позже."
            )
        except Exception:
            pass  # Silent failure if we can't even send an error message

async def combined_audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for audio inputs: either initial interview or voice query"""
    if context.user_data.get("chatting"):
        # Process as a voice query
        await handle_voice_query(update, context)
    else:
        # Process as interview audio and set up conversation context
        await handle_audio(update, context)

async def handle_unsupported_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unsupported media types with friendly warning"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(
        f"Unsupported file type received from User ID: {user_id}, Username: {username}"
    )
    warning_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Неподдерживаемый тип файла. Пожалуйста, отправьте аудиофайл с интервью или текстовое сообщение.",
    )

    context.user_data["unsupported_warning_msg_id"] = warning_msg.message_id

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process initial interview audio to establish conversation context
    
    This function:
    1. Downloads the audio to a temporary file
    2. Passes it to the conversation preparation module
    3. Processes any queued initial query if present
    """
    file_path = None
    processed_successfully = False
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    logger.info(f"Audio received from User ID: {user_id}, Username: {username}")

    if update.message.audio:
        media = update.message.audio
    elif update.message.voice:
        media = update.message.voice
    else:
        return

    try:
        audio_file: File = await media.get_file()
        
        logger.debug(f"Audio details - File ID: {media.file_id}, MIME Type: {media.mime_type}, File Size: {media.file_size} bytes")

        # Ensure user-specific download directory exists
        downloads_dir = os.path.join("downloads", str(user_id))
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Determine file extension from MIME type
        mime_type = media.mime_type
        extension_map = {
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
            "audio/wav": ".wav",
        }
        extension = extension_map.get(mime_type)
        
        if not extension:
            logger.warning(f"Unsupported audio format: {mime_type} from User ID: {user_id}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Неподдерживаемый формат аудио.",
            )
            return

        # Create and use temporary file
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False, dir=downloads_dir) as temp_file:
            file_path = temp_file.name
        
        logger.info(f"Downloading audio to: {file_path}")
        download_task = asyncio.create_task(audio_file.download_to_drive(file_path))
        await download_task

        # Remove any previous warnings if needed
        if context.user_data.get("unsupported_warning_msg_id"):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data["unsupported_warning_msg_id"],
                )
                logger.info("Deleted unsupported file warning message")
            except Exception as ex:
                logger.error(f"Could not delete unsupported warning message: {str(ex)}")

            context.user_data.pop("unsupported_warning_msg_id", None)

        # Process the audio
        status_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Аудио получено. Обрабатываю..."
        )

        logger.info(f"Starting conversation preparation with audio file: {file_path}")
        await prepare_conversation(file_path)
        logger.info("Conversation preparation completed successfully")

        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_message.message_id)

        # Handle any pending query
        pending_query = update.message.caption if update.message.caption else context.user_data.get("initial_query")
        if pending_query:
            # Clean up previous warning messages if needed
            if context.user_data.get("warning_msg_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id, 
                        message_id=context.user_data["warning_msg_id"]
                    )
                except Exception as ex:
                    logger.error(f"Could not delete warning message: {str(ex)}")
                context.user_data.pop("warning_msg_id", None)
                
            context.user_data["initial_query"] = pending_query

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

        # Enable chat mode
        context.user_data["chatting"] = True
        context.user_data.pop("initial_query", None)

    except Exception as e:
        logger.error(f"Error processing audio for User ID: {user_id}: {str(e)}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при обработке аудио.",
        )
    finally:
        # Clean up temporary file
        if processed_successfully and file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Removed temporary file: {file_path}")
            except Exception as remove_error:
                logger.error(f"Failed to remove temporary file {file_path}: {str(remove_error)}", exc_info=True)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process text queries in chat mode or queue them for later processing"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    user_query = update.message.text
    
    if context.user_data.get("chatting"):
        # Chat mode - process query immediately
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
        # Queue query for later processing after audio is received
        logger.warning(f"User ID: {user_id} attempted to send a query before audio was received")
        
        if "initial_query" not in context.user_data:
            # First query before audio
            context.user_data["initial_query"] = user_query
            warning_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио ещё не получено. Ваш запрос сохранён и будет обработан после получения аудио."
            )
            context.user_data["warning_msg_id"] = warning_msg.message_id
        else:
            # Additional queries before audio
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

async def handle_voice_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process voice messages as queries in chat mode
    
    This function:
    1. Downloads the voice message
    2. Transcribes it using the voice transcription service
    3. Processes the transcribed text as a chat query
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"Voice query received from User ID: {user_id}, Username: {username}")

    # Get the voice or audio media object
    media = update.message.voice if update.message.voice else (update.message.audio if update.message.audio else None)
    if not media:
        return

    # Set up temporary file
    extension = ".ogg"  # Default for Telegram voice messages
    downloads_dir = os.path.join("downloads", str(user_id))
    os.makedirs(downloads_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=extension, delete=False, dir=downloads_dir) as temp_file:
        file_path = temp_file.name

    try:
        # Download and transcribe the voice message
        audio_file: File = await media.get_file()
        logger.info(f"Downloading voice query to: {file_path}")
        await audio_file.download_to_drive(file_path)

        logger.info(f"Transcribing voice query")
        transcribed_text = await transcribe_voice(file_path)
        logger.info(f"Transcription result: {transcribed_text}")

        # Process the transcribed text
        processing_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Обрабатываю ваш запрос..."
        )
        try:
            response = await chat(transcribed_text)
            if response:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_msg.message_id)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=response,
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"Error during chat for UserID: {user_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке вашего запроса.",
            )
    except Exception as e:
        logger.error(f"Error processing voice query for UserID: {user_id}: {str(e)}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при обработке голосового запроса.",
        )
    finally:
        # Clean up temporary file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Removed temporary file: {file_path}")
            except Exception as remove_error:
                logger.error(f"Failed to remove temporary file {file_path}: {str(remove_error)}", exc_info=True)

def main():
    """Entry point: configure and start the Telegram bot"""
    logger.info("Starting Telegram bot application")
    try:
        application = ApplicationBuilder().token(TOKEN).build()

        # Register handlers in priority order
        handlers = [
            CommandHandler("start", start),
            CommandHandler("new", new),
            CommandHandler("help", help),
            MessageHandler(filters.AUDIO | filters.VOICE, combined_audio_handler),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_unsupported_file),
            MessageHandler(filters.COMMAND, unknown_command)  # Must be last
        ]
        
        for handler in handlers:
            application.add_handler(handler)

        # Register global error handler
        application.add_error_handler(error_handler)

        logger.info("All handlers registered, starting polling...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Failed to start the bot: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
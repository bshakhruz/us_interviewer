# app.py
import os
import tempfile
import mimetypes
from dotenv import load_dotenv

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


load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Здравствуйте! Отправьте мне аудио интервью"
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming audio files, transcribes them, and starts the conversation."""
    try:
        audio = update.message.audio
        audio_file: File = await audio.get_file()

        # 1. Create the "downloads" directory if it doesn't exist
        downloads_dir = "downloads"
        os.makedirs(downloads_dir, exist_ok=True)

        # 2. Determine the file extension based on MIME type (manual check)
        mime_type = audio.mime_type
        if mime_type == "audio/mpeg":
            extension = ".mp3"
        elif mime_type == "audio/ogg":
            extension = ".ogg"
        elif mime_type == "audio/mp4":
            extension = ".m4a"  # or ".mp4" depending on your needs
        elif mime_type == "audio/x-m4a":
            extension = ".m4a"
        elif mime_type == "audio/wav":
            extension = ".wav"
        else:
            extension = None  # Unsupported format

        # 3. Download the audio to a temporary file with the correct extension
        if extension:
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False, dir=downloads_dir) as temp_file:
                file_path = temp_file.name
                await audio_file.download_to_drive(file_path)
        else:
            # Handle unsupported file types
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Неподдерживаемый формат аудио.",
            )
            return  # Exit the function

        is_received_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Аудио получено. Обрабатываю..."
        )

        await prepare_conversation(file_path)  # Pass the file path

        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=is_received_msg.message_id)

        # Check for an immediate text message after the audio
        # This is a simplified approach.  More robust solutions might involve
        # a state machine or a more complex way to track the conversation flow.
        if update.message.caption:  # Check if there's a caption
            initial_query = update.message.caption
            context.user_data["initial_query"] = initial_query
            query_process_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио обработано. Обрабатываю ваш запрос...",
            )
            try:
                response = await chat(initial_query)

                if response:

                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query_process_msg.message_id)
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=response,
                        parse_mode="HTML"
                    )
            except Exception as e:
                print(f"Error during initial chat: {e}")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка при обработке вашего запроса.",
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Аудио обработано. Можете задавать вопросы.",
            )

        # Set a state to indicate that the bot is ready for chat
        context.user_data["chatting"] = True

    except Exception as e:
        print(f"Error processing audio: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при обработке аудио.",
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages (user queries) if the bot is in chat mode."""
    if context.user_data.get("chatting"):
        user_query = update.message.text
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Обрабатываю ваш запрос..."
        )
        try:
            response = await chat(user_query)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=response,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Error during chat: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке вашего запроса.",
            )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Сначала отправьте аудио.",
        )


def main():
    application = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler("start", start)
    audio_handler = MessageHandler(filters.AUDIO, handle_audio)
    text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)  # Handle text, excluding commands

    application.add_handler(start_handler)
    application.add_handler(audio_handler)
    application.add_handler(text_handler)

    print("Starting the bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
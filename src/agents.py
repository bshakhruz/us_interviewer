import io

import aiofiles

from dotenv import load_dotenv
from openai import AsyncOpenAI


load_dotenv()

client = AsyncOpenAI()

conversation_history = []

async def prepare_conversation(audio_file_path: str):
    """
    Transcribes the given audio, and then initializes the conversation history with
    system instructions and initial context messages.

    Args:
        audio_file_path (str): The path to the audio file to transcribe.
    """
    transcript = await transcribe_audio(audio_file_path)
    system_message = (
        "You are a US embassy expert interview officer assistant. Based on the following interview transcript, "
        "summarize and answer any questions the user has about the interview.\n"
        "\n"
        "**Supported languages**\n"
        "you can speak answer in Russian, Uzbek (both Latin & Cyrillic), and English\n"
        "\t- e.i,. if user query comes in EN => respond in EN\n"
        "\t- e.i., if user query comes in RU => respond in RU alphabet: абс\n"
        "\t-e.i., if user query comes in UZ => you have two options: Latin: abc; Cyrillic: абсд; so depends on user query.\n"
        "Always follow above language instruction unless user specifies in his user query (then override and follow their instruction.)\n"
        "\n"
        ""
        "**Formatting Output**\n"
        "for instance not like **Main Points** but retun like this 1. <b> First Point</b> ... to all of points apply this."
        "return All output is sent to telegram bot. Format bold points or any headings with html tags <b></b> instead of **.\n"

    )
    global conversation_history
    # Clear any previous conversation and initialize the chat context.
    conversation_history = [{
        "role": "system",
        "content": system_message
    },
    {
        "role": "user",
        "content": f"Interview transcript as the context: \n{transcript}"
    },
    {
        "role": "assistant",
        "content": "Ask anything about interview..."
    }]

#=== US Embassy Interview Assistant Agent ===#
async def chat(user_query: str):
    """
    Sends the user query (prefixed by a predefined text) appended to the conversation history,
    then calls the model and returns the assistant's reply.

    Args:
        user_query (str): The user's query about the interview.

    Returns:
        str: The assistant's full response text.
    """

    # Append the user query with the specified format.
    conversation_history.append({
        "role": "user",
        "content": f"Here is user query: \n{user_query}"
    })

    # Call the model and get response
    response = await client.responses.create(
        model="gpt-4o-mini",
        input=conversation_history,
        stream=False # set to 'True' if u want to stream
    )

    # Accumulate assistant's response text as it arrives.
    # assistant_reply = ""
    # async for event in response:
    #     if hasattr(event, "delta") and event.delta:
    #         # print(event.delta, end="", flush=True)
    #         assistant_reply += event.delta

    # print("\n" + "-" * 20)
    # Append the assistant's full reply to the conversation history.
    
    if response:
        # print(response.output_text)
        conversation_history.append({
            "role": "assistant",
            "content": response.output_text
        })

        return response.output_text


# === Audio Transcriber Agent ===#
async def transcribe_audio(audio_file_path: str):
    """
    Transcribes the audio from the given file path using OpenAI's transcription API.

    Args:
        audio_file_path (str): The path to the audio file.

    Returns:
        str: The transcribed text from the audio file.
    """
    # Read the file asynchronously into memory
    async with aiofiles.open(audio_file_path, "rb") as afile:
        file_bytes = await afile.read()

    file_stream = io.BytesIO(file_bytes)
    file_stream.name = audio_file_path

    with open(audio_file_path, "rb") as audio_file:
        # start = time.time()
        transcription = await client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe", # gpt-4o-mini-transcribe, gpt-4o-transcribe
            file=audio_file,
            prompt= (
                        "The following conversation is a US embassy interview between a US embassy officer "
                        "and an applicant.\n\n"
                        "Return like this following this format:\n\n"
                        "Output:\n"
                        "Interviewer: <response>\n"
                        "Applicant: <response>\n"
                        "Interviewer: <response>\n"
                        "Applicant: <response>\n"
                        "..."
                    ),
    stream=False # set to True to stream
    )
    # end = time.time()
    # full_text = ""
    # async for event in transcription:
    #     # If the event is a delta event, append its delta to full_text
    #     if hasattr(event, "delta"):
    #         # You can print the token as it arrives or accumulate it
    #         print(event.delta, end="", flush=True)
    #         full_text += event.delta

    # print("\n")
    # print("-" * 25)
    # print(f"Time taken: {end-start} seconds")
    
    return transcription.text

async def transcribe_voice(audio_file):

    """
    Transcribes the audio from the given file path using OpenAI's transcription API.

    Args:
        audio_file (str): The path to the audio file.

    Returns:
        str: The transcribed text from the audio file.
    """
    # Read the file asynchronously into memory
    async with aiofiles.open(audio_file, "rb") as afile:
        file_bytes = await afile.read()

    file_stream = io.BytesIO(file_bytes)
    file_stream.name = audio_file

    with open(audio_file, "rb") as audio_file:
        # start = time.time()
        transcription = await client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe", # gpt-4o-mini-transcribe, gpt-4o-transcribe
            file=audio_file,
            prompt= (
                        "Transcribe as it is clearly. Incoming audio files are in Russian, Uzbek, and English languages."
                    ),
    stream=False # set to True to stream
    )
    # end = time.time()
    # full_text = ""
    # async for event in transcription:
    #     if hasattr(event, "delta"):
    #         print(event.delta, end="", flush=True)
    #         full_text += event.delta

    # print("\n")
    # print("-" * 25)
    # print(f"Time taken: {end-start} seconds")
    
    return transcription.text
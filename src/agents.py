import os
import asyncio
import time

from dotenv import load_dotenv
from pathlib import Path
load_dotenv()

from openai import OpenAI, AsyncOpenAI

client = AsyncOpenAI()

conversation_history = []

async def prepare_conversation(audio_file_path: str):
    """
    Transcribes the given audio, and then initializes the conversation history with
    system instructions and initial context messages.
    """
    transcript = await transcribe_audio(audio_file_path)
    system_message = (
    "You are a US embassy interview officer assistant. Based on the following interview transcript, "
    "summarize and answer any questions the user has about the interview.\n"
    "\n"
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
    then calls the model and streams the assistant's reply.
    Returns the assistant’s full response text.
    """

    # Append the user query with the specified format.
    conversation_history.append({
    "role": "user",
    "content": f"Here is user query: \n{user_query}"
    })

    # Call the model and stream response
    response = await client.responses.create(
        model="gpt-4o-mini",
        input=conversation_history,
        stream=True  # stream tokens so that the answer appears gradually.
    )

    # Accumulate assistant's response text as it arrives.
    assistant_reply = ""
    async for event in response:
        if hasattr(event, "delta") and event.delta:
            print(event.delta, end="", flush=True)
            assistant_reply += event.delta

    print("\n" + "-" * 20)
    # Append the assistant's full reply to the conversation history.
    conversation_history.append({
        "role": "assistant",
        "content": assistant_reply
    })

    return assistant_reply


# === Audio Transcriber Agent ===#
async def transcribe_audio(audio_file_path: str):

    full_text = ""

    with open(audio_file_path, "rb") as audio_file:
        start = time.time()
        transcription = await client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe", # gpt-4o-mini-transcribe, gpt-4o-transcribe
            file=audio_file,
            
            prompt=(
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
    stream=True
    )
    end = time.time()
    async for event in transcription:
        # If the event is a delta event, append its delta to full_text
        if hasattr(event, "delta"):
            # You can print the token as it arrives or accumulate it
            print(event.delta, end="", flush=True)
            full_text += event.delta

    print("\n")
    print("-" * 25)
    print(f"Time taken: {end-start} seconds")
    
    return full_text

async def main():

    # audio_file= r"c:\Users\user\Downloads\Sukhrob Mock interview.m4a"
    audio_file = "audio_2025-04-02_13-01-04.ogg"

    # Transcribe the audio file
    print("Transcribing audio file...\n")
    audio_transcript = await transcribe_audio(audio_file)

    # Add initial conversation messages.
    conversation_history.append({
        "role": "user",
        "content": f"Interview transcript as the context: \n{audio_transcript}"
    })
    conversation_history.append({
        "role": "assistant",
        "content": "Ask anything about interview..."
    })

    # Continue chatting until the user ends the conversation.
    print("\n=== You may now ask questions about the interview transcript ===")
    while True:
        try:
            # Get user query from the command line
            user_query = input("\nYour query (or type 'exit' to quit): ")
            if user_query.strip().lower() == "exit":
                print("Exiting conversation.")
                break

            # Send the user query and get a stateful answer
            print("\nAssistant reply:")
            await chat(user_query)

            # Optionally, print the final full response text (already printed via streaming)
            # print(chat_response)
        except KeyboardInterrupt:
            print("\nConversation interrupted.")
            break

if __name__=="__main__":
    asyncio.run(main())
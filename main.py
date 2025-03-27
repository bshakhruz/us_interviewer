import asyncio

from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()


async def main():

    client = AsyncOpenAI()


    audio_file= open("/path/to/file/audio.mp3", "rb")

    transcription = await client.audio.transcriptions.create(
        model="gpt-4o-transcribe", 
        file=audio_file,
        prompt="The following conversation is a lecture about the recent developments around OpenAI, GPT-4.5 and the future of AI.",

    )

    print(transcription.text)

if __name__=="__main__":
    asyncio.run(main())
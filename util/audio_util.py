from io import BytesIO
from pydub import AudioSegment
from services.openai_service import openai_service
from lib.log import logger

def speech_to_text(audio_file):
    """
    Convert speech to text using OpenAI's Whisper model.
    """
    try:
        transcript = openai_service.client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file
        )
        return transcript.text
    except Exception as e:
        logger.error(f"Error in speech to text conversion: {str(e)}", exc_info=True)
        raise

def text_to_speech(text: str, speaker: str, language: str = "en"):
    """
    Convert text to speech using OpenAI's TTS model.
    """
    try:
        response = openai_service.client.audio.speech.create(
            model="tts-1",
            input=text,
            voice="echo" if speaker == "male" else "shimmer",  # TODO: To handle other language and accents 
        )
        
        # Stream the audio directly into memory using BytesIO
        audio_content = BytesIO(response.content)
        
        # Load the audio into an AudioSegment for further processing
        audio_segment = AudioSegment.from_file(audio_content, format="mp3")
        logger.debug(f"Generated audio successfully for {speaker} : {text} ")
        return audio_segment
    except Exception as e:
        logger.error(f"Error in text to speech conversion: {str(e)}", exc_info=True)
        raise


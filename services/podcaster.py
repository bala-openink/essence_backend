import os
import time
import hashlib
from io import BytesIO
from typing import List, Dict, Optional
import random
import subprocess

from werkzeug.exceptions import BadRequest
from dotenv import load_dotenv

from pydub import AudioSegment
from openai import OpenAI
from google.cloud import texttospeech

from services import util
from models import AudioStoryRequest
from lib.log import logger

load_dotenv()

client = OpenAI(
    # This is the default and can be omitted
    api_key=util.get_secret("OPENAI_API_KEY")
)

# os.environ["PATH"] += os.pathsep + os.path.join(os.getcwd(), "bin")

# Dictionary containing the transition messages
category_transitions = {
    1: "Now, let’s dive into the latest in {category}.",
    2: "Up next, here’s what’s happening in {category}.",
    3: "Shifting focus, it’s time for some {category} updates.",
    4: "And now, let’s explore today’s top {category} stories.",
    5: "Moving on, here’s what’s trending in {category}.",
    6: "Next, we’re diving into the world of {category}.",
    7: "Get ready for the latest in {category} news.",
    8: "Switching gears, let’s talk about {category}.",
    9: "Now, let’s shift our attention to {category}.",
    10: "Time to catch up on the latest in {category}."
}


# In-memory cache dictionary
cache: Dict[str, AudioSegment] = {}

def generate_hash(text_summary: str) -> str:
    """Generates a hash for the given text_summary."""
    return hashlib.sha256(text_summary.encode()).hexdigest()


def generate_audio_story(request: AudioStoryRequest):
        text_summary = request.text_summary
        if text_summary is None:
            raise BadRequest("Text summary is provided. Cannot continue")

        # Generate hash of the text_summary
        request_hash = generate_hash(text_summary)

        # Check if result is in cache
        if request_hash in cache:
            return cache[request_hash]

        # Step 1: Generate Conversational Podcast Content
        conversation = generate_conversation(
            text_summary=text_summary,
            length=request.length,
            language=request.language,
            region=request.region,
            two_speakers=request.two_speakers,
            user_name=request.user_name
        )
        
        # Step 2: Convert Text to Audio
        audio_segments = []
        for speaker, text in conversation.items():
            # Hack to remove the extra prefixes added by GPT
            text = text.split(": ", 1)[1] if text.startswith(("Emily:", "Harry:")) else text
            audio_segment = generate_audio(speaker, text, request.language)
            audio_segments.append(audio_segment)

        # Step 3: Combine Audio Segments
        final_audio = merge_audio_segments(audio_segments)

        # Step 4: Add Background Music if Required
        if request.add_background:
            final_audio = add_bg(final_audio)

        # Store the audio in cache and return
        cache[request_hash] = final_audio
        return final_audio    

def generate_intro_audio(userName: str = "there", twoSpeakers: bool = "false"):
    segments = []
    if twoSpeakers:
        welcome_message = f"Hi {userName} - Good morning. Welcome to ESSENCE - Your personalised news podcast, presented by Harry and Emily.  Let's dive into the 'essence of today's top stories --- made just for you."
        hello_message_male = "... Good morning Emily"
        hello_message_female = "... Good morning Harry... lets get started !!!"
        segments.append(generate_audio("male", welcome_message))
        segments.append(generate_audio("male", hello_message_male))
        segments.append(generate_audio("female", hello_message_female))
        intro_segment = merge_audio_segments(segments)

    else:
        welcome_message = f"Hi {userName} - Good morning. Welcome to ESSENCE - Your personalised news podcast, presented by Harry.  Let's dive into the 'essence of today's top stories --- made just for you."
        intro_segment = generate_audio("male", welcome_message)

    intro_segment = add_bg_for_intro(intro_segment)
    return intro_segment

def generate_category_transition_audio(categoryName):
    transition_message = get_random_transition(categoryName)
    transition_audio = generate_audio(random.choice(['male', 'female']), transition_message)
    transition_segment = add_bg(transition_audio)
    return transition_segment

def get_random_transition(categoryName):
    # Select a random transition message
    message_id = random.randint(1, 10)
    message = category_transitions[message_id]
    # Replace the placeholder with the actual category
    return message.format(category=categoryName)


# TODO: Support for different lengths - short & long forms
def generate_conversation(text_summary: str, length: str, language: str, region: str, two_speakers: bool, user_name: str):
    word_count = 70 if length == "short" else 500

    single_speaker_prompt = (
        "Convert the following news summary into a podcast segment that feels like part of an ongoing monologue delivered by one speaker, Harry. "
        "Maintain a semi-formal, neutral, and unbiased tone while ensuring the content is engaging and flows naturally. Include natural human elements such as brief pauses by adding extra spaces or hyphens, sounds like hmm.., aah... to make it real"
        "Use natural transitions as if the speaker is moving on from the previous topic or wrapping up thoughts. Ensure the segment stands alone but feels like it fits naturally into a larger show"
        f"The monologue should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"Target a monologue length of approximately {word_count} words, and make sure it does not exceed {word_count + 10} words. If necessary, condense or trim the content to stay within the limit, but do not lose the essence of the news. "
        "Please return the output as valid JSON. Ensure the response is a well-formed JSON object with no extra text or formatting."
        "Expected JSON format {\"male\": \"male dialogue\"}. Avoid extra prefix in the output with the presenter name, Harry. "
        f"Here is the summary to convert: '{text_summary}'"
    )

    two_speakers_prompt = (
        "Convert the following news summary into a podcast segment that feels like part of an ongoing conversation between two speakers, Harry and Emily, with each providing extended commentary before the other responds, maintaining a semi-formal news reporting style. The dialogue should flow smoothly without formal introductions, greetings or sign-offs."
        "Maintain a semi-formal, neutral, and unbiased tone while ensuring the content is engaging and flows naturally. Include natural human elements such as brief pauses by adding extra spaces or hyphens, sounds like hmm.., aah... to make it real"
        "Use natural transitions as if the speakers are moving on from the previous topic or wrapping up thoughts. Ensure the segment stands alone but feels like it fits naturally into a larger show"
        f"The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"Target a conversation length of approximately {word_count} words, and make sure it does not exceed {word_count + 10} words. If necessary, condense or trim the content to stay within the limit, but do not lose the essence of the news. "
        "Please return the output as valid JSON. Ensure the response is a well-formed JSON object with no extra text or formatting."
        "Expected JSON format {\"male\": \"male dialogue\", \"female\": \"female dialogue\"}. Avoid any extra prefix in the output with the presenter names, Harry and Emily."
        f"Here is the summary to convert: '{text_summary}'"
    )


    prompt = (
        "I will provide a news summary, and your task is to turn it into a natural-sounding dialogue"
        f"{'Include two speakers, Harry and Emily, with each providing extended commentary before the other responds, maintaining a semi-formal news reporting style. Address each other by names - the male as Harry and female as Emily. The dialogue should flow smoothly without formal introductions, greetings or sign-offs, as this is a part of an already ongoing conversation between them' if two_speakers else 'Include only one speaker, Harry delivering in a semi-formal style'} "
        f"The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"{f'Occasionally, address the user by their name, {user_name}' if user_name is not None else ''}"
        f"Target a conversation length of approximately {word_count} words, and make sure it does not exceed {word_count + 10} words. If necessary, condense or trim the content to stay within the limit, but do not lose the essence of the news. "
        f"Return the conversation as valid clean JSON in the format {{\"male\": \"male dialogue\"{', \"female\": \"female dialogue\"' if two_speakers else ''}}}. "
        "Please avoid extra prefix in the output with presenter names, Harry, Emily, etc. "
        f"Here is the summary to convert: '{text_summary}'"
    )

    # prompt = (
    #     f"Create a podcast conversation based on the following summary: '{text_summary}'. "
    #     f"The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region. "
    #     f"Ensure the conversation fits the region's typical news reporting tone and style. "
    #     f"{'Include two speakers, a male and a female, delivering news updates with each providing extended commentary before the other responds, maintaining a semi-formal news reporting style.' if two_speakers else 'Include only one speaker delivering a news report in a semi-formal style.'} "
    #     f"Target a conversation length of approximately {word_count} words. "
    #     "Return the conversation as valid JSON with no additional text. Use keys 'male' and 'female' for two speakers, or 'speaker' for one speaker. "
    #     "The output should be a clean JSON object with no prefixes or extra formatting."
    # )

    prompt = two_speakers_prompt if two_speakers else single_speaker_prompt

    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        model="gpt-3.5-turbo",
        max_tokens=1000,
        temperature=0.2,  # Adjust for more deterministic output
        top_p=1,
        frequency_penalty=0.0,
        presence_penalty=0.0
    )

    conversation = response.choices[0].message.content
    logger.info(conversation)
    
    try:
        # Convert the JSON response into a Python dictionary
        conversation_json = eval(conversation)
    except SyntaxError as e:
        raise ValueError("Failed to parse JSON response from OpenAI: " + str(e))
    
    return conversation_json

def generate_audio(speaker: str, text: str, language: str = "en"):
    return generate_audio_openai(speaker, text, language)

def generate_audio_openai(speaker: str, text: str, language: str = "en"):
    response = client.audio.speech.create(
        model="tts-1",
        input=text,
        voice="echo" if speaker == "male" else "shimmer",  # TODO: To handle other language and accents 
    )
    
    # Stream the audio directly into memory using BytesIO
    audio_content = BytesIO(response.content)
    
    # Load the audio into an AudioSegment for further processing
    audio_segment = AudioSegment.from_file(audio_content, format="mp3")
    logger.info(f"Generated audio successfully for {speaker} : {text} ")
    return audio_segment

def generate_audio_google(speaker: str, text: str, language: str = "en"):
    client = texttospeech.TextToSpeechClient()

    input_text = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code="en-GB",
        name="en-GB-Studio-B" if speaker == "male" else "en-GB-Studio-C",
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.2
    )

    response = client.synthesize_speech(
        request={"input": input_text, "voice": voice, "audio_config": audio_config}
    )

    # Stream the audio directly into memory using BytesIO
    audio_content = BytesIO(response.audio_content)
    
    # Load the audio into an AudioSegment for further processing
    audio_segment = AudioSegment.from_file(audio_content, format="mp3")
    logger.info(f"Generated audio from google tts successfully for {speaker} : {text} ")
    return audio_segment

def merge_audio_segments(audio_segments):
    combined = AudioSegment.silent(duration=0)
    for segment in audio_segments:
        combined += segment
    logger.info(f"merged succesfully {len(audio_segments)} segments")
    return combined

def add_bg(audio: AudioSegment):
    background_music = AudioSegment.from_file("resources/music/bg2.mp3")
    # Set volume levels (in dB)
    conversation_background_volume = -20  # Reduced volume during conversation

    # Adjust the volume of the background music for different segments
    background_conversation = background_music + conversation_background_volume

    # Create the final podcast audio
    one_second_bg = background_conversation[:1000]
    audio_with_bg_intro = one_second_bg + audio
    podcast_audio = audio_with_bg_intro.overlay(background_conversation)

    logger.info("Added background music successfully...")
    return podcast_audio

def add_bg_for_intro(audio: AudioSegment):
    duration_ms = len(audio)

    background_music = AudioSegment.from_file("resources/music/intro_bg.mp3")
    # Set volume levels (in dB)
    intro_outro_volume = -10  # Original volume
    conversation_background_volume = -20  # Reduced volume during conversation

    # Adjust the volume of the background music for different segments
    background_intro = background_music[:2000] + intro_outro_volume
    background_conversation = background_music[2000:2000+duration_ms] + conversation_background_volume
    background_outro = background_music[2000+duration_ms:2000+duration_ms+2000] + intro_outro_volume

    # Create the final podcast audio
    podcast_audio = background_intro
    podcast_audio += audio
    podcast_audio = podcast_audio.overlay(background_conversation, position=2000)
    podcast_audio += background_outro

    logger.info("Added background music successfully...")
    return podcast_audio

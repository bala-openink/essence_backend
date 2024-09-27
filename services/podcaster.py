import os
import time
import hashlib
from io import BytesIO
from typing import List, Dict, Optional
import random
import subprocess
import boto3

from werkzeug.exceptions import BadRequest

from pydub import AudioSegment
from openai import OpenAI
from google.cloud import texttospeech

from services import utilities
from models import AudioStoryRequest
from lib.log import logger
from lib import db


client = OpenAI(
    # This is the default and can be omitted
    api_key=utilities.get_secret("OPENAI_API_KEY")
)

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

def generate_intro_audio(userName='there', isFirstTimeEver=False, isFirstTimeToday=False, timeOfDay='day', twoSpeakers=True):
    # Determine the greeting based on time of day
    if timeOfDay.lower() == 'morning':
        greeting = "Good morning"
        context = "I hope your day is off to a great start."
        dive_in = "Let's kick off your morning with today's top stories."
    elif timeOfDay.lower() == 'afternoon':
        greeting = "Good afternoon"
        context = "I hope your day is going well so far."
        dive_in = "Let's catch you up on the latest news for your afternoon."
    elif timeOfDay.lower() == 'evening':
        greeting = "Good evening"
        context = "I hope you've had a productive day."
        dive_in = "Let's wrap up your day with the most important stories."
    else:
        greeting = "Hello"
        context = "I hope you're having a great day."
        dive_in = "Let's dive into the top stories."

    welcome_message_first = ""
    welcome_message_second = ""
    
    # Create the welcome message
    if isFirstTimeEver:
        two_speaker_intro = "We're Harry and Emily, your news presenters...."
        speaker_intro = "I'm Harry... your news presenter...."

        welcome_message_first = (
            f"{greeting}, {userName}! Welcome to ESSENCE - your personalized news podcast. "
            "We're excited to have you here. "
        )

        welcome_message_second = (
            f"{two_speaker_intro}" if twoSpeakers else f"{speaker_intro}"
            f"{context} {dive_in}"
        )
    elif isFirstTimeToday:
        two_speaker_intro = "As always, I'm Emily, joined by Harry...."
        speaker_intro = "Its Harry again..."

        welcome_message_first = (
            f"{greeting}, {userName}! Welcome back to ESSENCE. "
        )

        welcome_message_second = (
            f"{two_speaker_intro}" if twoSpeakers else f"{speaker_intro}"
            f"{context} {dive_in}"
        )
    else:
        welcome_message_first = (
            f"{greeting}, {userName}! Welcome back to ESSENCE. "
        )
        welcome_message_second = (
            f"{context} Let's continue with the latest stories."
        )

    # Generate the audio
    if twoSpeakers:
        male_intro = f"{welcome_message_first}"
        female_intro = f"{welcome_message_second}"
        male_segment = generate_audio("male", male_intro)
        female_segment = generate_audio("female", female_intro)
        intro_segment = merge_audio_segments([male_segment, female_segment])
    else:
        intro_segment = generate_audio("male", f"{welcome_message_first} {welcome_message_second}")

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
    word_count = 40 if length == "short" else 500

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
    logger.debug(conversation)  # Changed from info to debug
    
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
    logger.debug(f"Generated audio successfully for {speaker} : {text} ")  # Changed from info to debug
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
    logger.debug(f"Generated audio from google tts successfully for {speaker} : {text} ")  # Changed from info to debug
    return audio_segment

def merge_audio_segments(audio_segments):
    combined = AudioSegment.silent(duration=0)
    for segment in audio_segments:
        combined += segment
    logger.debug(f"merged succesfully {len(audio_segments)} segments")  # Changed from info to debug
    return combined

def add_bg(audio: AudioSegment):
    background_music = AudioSegment.from_file("resources/music/bg2.mp3")
    # Set volume levels (in dB)
    conversation_background_volume = -25  # Reduced volume during conversation

    # Adjust the volume of the background music for different segments
    background_conversation = background_music + conversation_background_volume

    # Create the final podcast audio
    one_second_bg = background_conversation[:1000]
    audio_with_bg_intro = one_second_bg + audio
    podcast_audio = audio_with_bg_intro.overlay(background_conversation)

    logger.debug("Added background music successfully...")  # Changed from info to debug
    return podcast_audio

def add_bg_for_intro(audio: AudioSegment):
    duration_ms = len(audio)

    background_music = AudioSegment.from_file("resources/music/bg2.mp3")
    # Set volume levels (in dB)
    intro_outro_volume = -10  # Original volume
    conversation_background_volume = -25  # Reduced volume during conversation

    # Adjust the volume of the background music for different segments
    background_intro = background_music[:2000] + intro_outro_volume
    background_conversation = background_music[2000:2000+duration_ms] + conversation_background_volume
    background_outro = background_music[2000+duration_ms:2000+duration_ms+2000] + intro_outro_volume

    # Create the final podcast audio
    podcast_audio = background_intro
    podcast_audio += audio
    podcast_audio = podcast_audio.overlay(background_conversation, position=2000)
    podcast_audio += background_outro

    logger.debug("Added background music successfully...")  # Changed from info to debug
    return podcast_audio


def generate_intro_audio_files(user_name, user_id):
    logger.info(f"Generating intro audio files for user {user_id}")
    try:
        user_table = db.get_user_table()
        user = user_table.get(user_id)
        if not user:
            raise BadRequest("User not found")

        # If user doesn't have intro_audio_urls or only the first intro audio is generated, generate them again
        if not user.get('intro_audio_urls') or len(user.get('intro_audio_urls', [])) < 2:
            combinations = [
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "morning"},
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "afternoon"},
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "evening"},
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "day"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "morning"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "afternoon"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "evening"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "day"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "morning"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "afternoon"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "evening"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "day"},
            ]

            audio_urls = {}
            first_audio_created = False

            for combo in combinations:
                intro_segment = generate_intro_audio(
                    userName=user_name,
                    isFirstTimeEver=combo["is_first_time_ever"],
                    isFirstTimeToday=combo["is_first_time_today"],
                    timeOfDay=combo["time_of_day"],
                    twoSpeakers=True
                )

                intro_audio = BytesIO()
                intro_segment.export(intro_audio, format="mp3")
                intro_audio.seek(0)

                key = f"{combo['is_first_time_ever']}_{combo['is_first_time_today']}_{combo['time_of_day']}"
                s3_key = f"{user_id}/intro/{key}"
                s3_url = utilities.upload_audio_to_s3(s3_key, intro_audio)
                audio_urls[key] = s3_url
                logger.info(f"Created intro audio file for {s3_key} and uploaded to {s3_url}")

                # Update the database after the first audio file is created
                if not first_audio_created:
                    user["intro_audio_urls"] = audio_urls
                    db.get_user_table().addOrUpdate(user)
                    first_audio_created = True
                    logger.info(f"Updated user {user_id} with first intro audio URL")

            # Update the user table with the audio URLs
            user["intro_audio_urls"] = audio_urls
            db.get_user_table().addOrUpdate(user)
            logger.info(f"Updated user {user_id} with all intro audio URLs")

    except Exception as e:
        logger.error(f"Error generating intro audio files: {str(e)}", exc_info=True)
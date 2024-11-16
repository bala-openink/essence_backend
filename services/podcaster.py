import hashlib
from io import BytesIO
from typing import Dict
import random

from werkzeug.exceptions import BadRequest

from pydub import AudioSegment

from services import utilities
from models.audio_story_request import AudioStoryRequest
from lib.log import logger
from db.factory import db_factory
from util import audio_util, llm_util

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
    10: "Time to catch up on the latest in {category}.",
}

# Add this list of transition phrases at the top of the file, after the imports
transition_phrases = [
    "Speaking of...",
    "This reminds me of...",
    "Meanwhile,...",
    "Turning our attention to...",
    "This ties into...",
    "Interestingly,...",
    "On a related note,...",
    "In contrast,...",
    "Building on that,...",
    "Shifting our focus,...",
    "In other news,...",
    "Connecting the dots,...",
    "As we explore further,...",
    "Taking a different angle,...",
    "To put things in perspective,...",
]

# In-memory cache dictionary
cache: Dict[str, AudioSegment] = {}

user_repository = db_factory.get_user_repository()


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
        user_name=request.user_name,
        previous_article=request.previous_article,
        new_instructions=request.new_instructions,
    )

    # Step 2: Convert Text to Audio
    audio_segments = []
    
    # Process each line from the raw conversation string
    for line in conversation.strip().split('\n'):
        if '"male":' in line:
            speaker = "male"
            text = line.split('": "')[1].rstrip('",')
        elif '"female":' in line:
            speaker = "female"
            text = line.split('": "')[1].rstrip('",')
        else:
            continue
            
        # Hack to remove the extra prefixes added by GPT
        cleaned_text = text.split(": ", 1)[1] if text.startswith(("Emily:", "Harry:")) else text
        audio_segment = generate_audio(speaker, cleaned_text, request.language)
        audio_segments.append(audio_segment)

    # Step 3: Combine Audio Segments
    final_audio = merge_audio_segments(audio_segments)

    # Step 4: Add Background Music if Required
    if request.add_background:
        final_audio = add_bg(final_audio)

    # Store the audio in cache and return
    cache[request_hash] = final_audio
    return final_audio


def generate_intro_audio(
    userName="there",
    isFirstTimeEver=False,
    isFirstTimeToday=False,
    timeOfDay="day",
    twoSpeakers=True,
):
    # Determine the greeting based on time of day
    if timeOfDay.lower() == "morning":
        greeting = "Good morning"
        context = "I hope your day is off to a great start."
        dive_in = "Let's kick off your morning with today's top stories."
    elif timeOfDay.lower() == "afternoon":
        greeting = "Good afternoon"
        context = "I hope your day is going well so far."
        dive_in = "Let's catch you up on the latest news for your afternoon."
    elif timeOfDay.lower() == "evening":
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
            f"{two_speaker_intro}"
            if twoSpeakers
            else f"{speaker_intro}" f"{context} {dive_in}"
        )
    elif isFirstTimeToday:
        two_speaker_intro = "As always, I'm Emily, joined by Harry...."
        speaker_intro = "Its Harry again..."

        welcome_message_first = f"{greeting}, {userName}! Welcome back to ESSENCE. "

        welcome_message_second = (
            f"{two_speaker_intro}"
            if twoSpeakers
            else f"{speaker_intro}" f"{context} {dive_in}"
        )
    else:
        welcome_message_first = f"{greeting}, {userName}! Welcome back to ESSENCE. "
        welcome_message_second = f"{context} Let's continue with the latest stories."

    # Generate the audio
    if twoSpeakers:
        male_intro = f"{welcome_message_first}"
        female_intro = f"{welcome_message_second}"
        male_segment = generate_audio("male", male_intro)
        female_segment = generate_audio("female", female_intro)
        intro_segment = merge_audio_segments([male_segment, female_segment])
    else:
        intro_segment = generate_audio(
            "male", f"{welcome_message_first} {welcome_message_second}"
        )

    intro_segment = add_bg_for_intro(intro_segment)
    return intro_segment


def generate_category_transition_audio(categoryName):
    transition_message = get_random_transition(categoryName)
    transition_audio = generate_audio(
        random.choice(["male", "female"]), transition_message
    )
    transition_segment = add_bg(transition_audio)
    return transition_segment


def get_random_transition(categoryName):
    # Select a random transition message
    message_id = random.randint(1, 10)
    message = category_transitions[message_id]
    # Replace the placeholder with the actual category
    return message.format(category=categoryName)


# TODO: Support for different lengths - short & long forms
def generate_conversation(
    text_summary: str,
    length: str,
    language: str,
    region: str,
    two_speakers: bool,
    user_name: str | None,
    previous_article: str | None,
    new_instructions: str | None,
):
    word_count = 40 if length == "short" else 500

    transition_suggestion = transition_phrases[random.randint(1, 15)]

    single_speaker_prompt = (
        "Convert the following news summary into a podcast segment that feels like part of an ongoing monologue delivered by one speaker, Harry. "
        "Maintain a semi-formal, neutral, and unbiased tone while ensuring the content is engaging and flows naturally. "
        # "Include natural human elements such as brief pauses (using extra spaces or hyphens) and thoughtful sounds (like 'hmm..', 'ah...') to enhance realism. "
        # f"Use diverse and natural transitions between topics. For example, you can use transitions like this one: '{transition_suggestion}' "
        # f"Feel free to use this or come up with your own creative transitions that fit the context. "
        "Ensure the segment stands alone while fitting naturally into a larger show. "
        f"The monologue should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"Target a monologue length of approximately {word_count} words, not exceeding {word_count + 10} words. If necessary, condense content while preserving the news essence. "
        'Return the output as valid JSON, formatted as {"male": "male dialogue"}. Avoid prefixing with the presenter\'s name. '
    )

    single_speaker_female_prompt = (
        "Convert the following news summary into a podcast segment that feels like part of an ongoing monologue delivered by one speaker, Emily. "
        "Maintain a semi-formal, neutral, and unbiased tone while ensuring the content is engaging and flows naturally. "
        # "Include natural human elements such as brief pauses (using extra spaces or hyphens) and thoughtful sounds (like 'hmm..', 'ah...') to enhance realism. "
        # f"Use diverse and natural transitions between topics. For example, you can use transitions like this one: '{transition_suggestion}' "
        # f"Feel free to use this or come up with your own creative transitions that fit the context. "
        "Ensure the segment stands alone while fitting naturally into a larger show. "
        f"The monologue should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"Target a monologue length of approximately {word_count} words, not exceeding {word_count + 10} words. If necessary, condense content while preserving the news essence. "
        'Return the output as valid JSON, formatted as {"female": "female dialogue"}. Avoid prefixing with the presenter\'s name. '
    )

    two_speakers_prompt = (
        "Convert the following news summary into a podcast segment that feels like part of an ongoing conversation between two speakers, Harry and Emily, with each providing extended commentary before the other responds, maintaining a semi-formal news reporting style. The dialogue should flow smoothly without formal introductions, greetings or sign-offs."
        "Maintain a semi-formal, neutral, and unbiased tone while ensuring the content is engaging and flows naturally. "
        # "Include natural human elements such as brief pauses (using extra spaces or hyphens) and thoughtful sounds (like 'hmm..', 'ah...') to enhance realism. "
        # f"Use diverse and natural transitions between topics. For example, you can use transitions like this one: '{transition_suggestion}' "
        # f"Feel free to use this or come up with your own creative transitions that fit the context. "
        "Ensure the segment stands alone while fitting naturally into a larger show. "
        f"The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"Target a conversation length of approximately {word_count} words, not exceeding {word_count + 10} words. If necessary, condense content while preserving the news essence. "
        'Return the output as valid JSON, formatted as {"male": "male dialogue", "female": "female dialogue"}. Avoid any extra prefix in the output with the presenter names, Harry and Emily.'
    )

    prompt = (
        "I will provide a news summary, and your task is to turn it into a natural-sounding dialogue"
        f"{'Include two speakers, Harry and Emily, with each providing extended commentary before the other responds, maintaining a semi-formal news reporting style. Address each other by names - the male as Harry and female as Emily. The dialogue should flow smoothly without formal introductions, greetings or sign-offs, as this is a part of an already ongoing conversation between them' if two_speakers else 'Include only one speaker, Harry delivering in a semi-formal style'} "
        f"The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region. "
        f"{f'Occasionally, address the user by their name, {user_name}' if user_name is not None else ''}"
        f"Target a conversation length of approximately {word_count} words, not exceeding {word_count + 10} words. If necessary, condense content while preserving the news essence. "
        f"Return the conversation as valid clean JSON in the format {{\"male\": \"male dialogue\"{', \"female\": \"female dialogue\"' if two_speakers else ''}}}. "
        "Please avoid extra prefix in the output with presenter names, Harry, Emily, etc. "
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

    instructions = (
        two_speakers_prompt
        if two_speakers
        else random.choice([single_speaker_prompt, single_speaker_female_prompt])
    )

    if new_instructions:
        instructions = new_instructions

    conversation = llm_util.chat_with_openai(text_summary, instructions)
    logger.info(f"Conversation response: {conversation}")

    return conversation


def generate_audio(speaker: str, text: str, language: str = "en"):
    return audio_util.text_to_speech(text, speaker, language)


def merge_audio_segments(audio_segments):
    combined = AudioSegment.silent(duration=0)
    for segment in audio_segments:
        combined += segment
    logger.debug(
        f"merged succesfully {len(audio_segments)} segments"
    )  # Changed from info to debug
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
    background_conversation = (
        background_music[2000 : 2000 + duration_ms] + conversation_background_volume
    )
    background_outro = (
        background_music[2000 + duration_ms : 2000 + duration_ms + 2000]
        + intro_outro_volume
    )

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
        user = user_repository.get(user_id)
        if not user:
            raise BadRequest("User not found")

        # If user doesn't have intro_audio_urls or only the first intro audio is generated, generate them again
        if not user.intro_audio_urls or len(user.intro_audio_urls) < 2:
            combinations = [
                {
                    "is_first_time_ever": True,
                    "is_first_time_today": True,
                    "time_of_day": "morning",
                },
                {
                    "is_first_time_ever": True,
                    "is_first_time_today": True,
                    "time_of_day": "afternoon",
                },
                {
                    "is_first_time_ever": True,
                    "is_first_time_today": True,
                    "time_of_day": "evening",
                },
                {
                    "is_first_time_ever": True,
                    "is_first_time_today": True,
                    "time_of_day": "day",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": True,
                    "time_of_day": "morning",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": True,
                    "time_of_day": "afternoon",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": True,
                    "time_of_day": "evening",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": True,
                    "time_of_day": "day",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": False,
                    "time_of_day": "morning",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": False,
                    "time_of_day": "afternoon",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": False,
                    "time_of_day": "evening",
                },
                {
                    "is_first_time_ever": False,
                    "is_first_time_today": False,
                    "time_of_day": "day",
                },
            ]

            audio_urls = {}
            first_audio_created = False

            for combo in combinations:
                intro_segment = generate_intro_audio(
                    userName=user_name,
                    isFirstTimeEver=combo["is_first_time_ever"],
                    isFirstTimeToday=combo["is_first_time_today"],
                    timeOfDay=combo["time_of_day"],
                    twoSpeakers=True,
                )

                intro_audio = BytesIO()
                intro_segment.export(intro_audio, format="mp3")
                intro_audio.seek(0)

                key = f"{combo['is_first_time_ever']}_{combo['is_first_time_today']}_{combo['time_of_day']}"
                s3_key = f"{user_id}/intro/{key}"
                s3_url = utilities.upload_audio_to_s3(s3_key, intro_audio)
                audio_urls[key] = s3_url
                logger.info(
                    f"Created intro audio file for {s3_key} and uploaded to {s3_url}"
                )

                # Update the database after the first audio file is created
                if not first_audio_created:
                    user.intro_audio_urls = audio_urls
                    user_repository.update(user)
                    first_audio_created = True
                    logger.info(f"Updated user {user_id} with first intro audio URL")

            # Update the user with all audio URLs
            user.intro_audio_urls = audio_urls
            user_repository.update(user)
            logger.info(f"Updated user {user_id} with all intro audio URLs")

    except Exception as e:
        logger.error(f"Error generating intro audio files: {str(e)}", exc_info=True)

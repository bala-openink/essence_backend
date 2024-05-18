import time
import json

# from transformers import pipeline

from openai import OpenAI

from services import audio_processor
from services import util
from lib import db, log
import config

logger = log.setup_logger()

client = OpenAI(
    # This is the default and can be omitted
    api_key=util.get_secret("OPENAI_API_KEY")
)

# Convenience method to remove unnecessary fields before responding to client
def strip_for_transport(item):
    if item and item["transcript"]:
        item["transcript"] = None
        item["audio_summary_url"] = None
    return item

def process_in_stream(user_id, id, clean_url, transcript, instructions, include_audio, item):
    if not item:
        item = {
            "user_id": user_id or config.DEFAULT_USERNAME,
            "id": id,
            "url": clean_url,
            "transcript": transcript,
            "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }

    # Make the GPT call to summarize the transcript and yield immediately
    summary_instructions = build_instructions("summary")
    summary_para = gpt(transcript, summary_instructions)
    if summary_para:
        item["text_summary"] = summary_para
        db.get_summary_table().addOrUpdate(item)
        yield json.dumps(strip_for_transport(item)) + "\n\n";

    # Make the GPT call to infer other aspects and yield immediately
    inference_instructions = build_instructions("inference")
    inference = gpt(transcript, inference_instructions)
    try:
        inference_json = json.loads(inference)
        item.update(inference_json)
        db.get_summary_table().addOrUpdate(item)
        yield json.dumps(strip_for_transport(item)) + "\n\n";
    except json.JSONDecodeError:
        print("Error: Invalid JSON response from OpenAI API.")
    
    # Create an audio summary and yield
    if include_audio and summary_para:
        audio_file_url, audio_file_local = audio_processor.text_to_audio_polly(id, summary_para)
        item["audio_summary_url"] = audio_file_url
        db.get_summary_table().addOrUpdate(item)
        audio_url_public = util.generate_audio_url_public(audio_file_url)
        if audio_url_public:
            item["audio_url"] = audio_url_public
            yield json.dumps(strip_for_transport(item)) + "\n\n";


def text_summary(user_id, id, clean_url, transcript, item):
    if not item:
        item = {
            "user_id": user_id or config.DEFAULT_USERNAME,
            "id": id,
            "url": clean_url,
            "transcript": transcript,
            "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }

    # Make the GPT call to summarize the transcript
    summary_instructions = build_instructions("summary")
    summary_para = gpt(transcript, summary_instructions)
    if summary_para:
        item["text_summary"] = summary_para
        db.get_summary_table().addOrUpdate(item)
        return json.dumps(strip_for_transport(item))


def inference(user_id, id, clean_url, transcript, include_audio, item):
    if not item:
        item = {
            "user_id": user_id or config.DEFAULT_USERNAME,
            "id": id,
            "url": clean_url,
            "transcript": transcript,
            "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }

    # Make the GPT call to infer other aspects 
    inference_instructions = build_instructions("inference")
    inference = gpt(transcript, inference_instructions)
    try:
        inference_json = json.loads(inference)
        # Adding the shortened URL to the tweet response from GPT
        inference_json["tweet"] = inference_json["tweet"] + " - " + util.shorten_url(clean_url)
        item.update(inference_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON response from OpenAI API.")
    
    # Create an audio summary
    audio_file_url = None
    if include_audio and item.get("text_summary"):
        audio_file_url, audio_file_local = audio_processor.text_to_audio_polly(id, item["text_summary"])
        item["audio_summary_url"] = audio_file_url

    db.get_summary_table().addOrUpdate(item)

    if audio_file_url:
        audio_url_public = util.generate_audio_url_public(audio_file_url)
        if audio_url_public:
            item["audio_url"] = audio_url_public
    
    return json.dumps(strip_for_transport(item))

def gpt(text, instructions):
    return gpt_with_openai(text, instructions)

def gpt_with_openai(text, instructions, model="gpt-3.5-turbo", temperature=0.5, max_tokens=4000):
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"{text}"}
        ],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,  # Adjust for more deterministic output
        top_p=1,
        frequency_penalty=0.0,
        presence_penalty=0.0
    )

    summary = response.choices[0].message.content.strip()
    print(f"Summary :: {summary}")
    return summary

def build_instructions(type):
    inference_instructions = f"""
    You are an AI assistant specializing in text analysis. Study the article thoroughly and provide the following information in a JSON format:

    {{
    "depth":"On a scale of 1 to 5, 1 for shallow and 5 for deep, rate how well the key topic is covered in the article",
    "tone": "The overall tone of the article in one word(e.g., formal, informal, objective, subjective, serious, humorous, inspirational, relaxed, cynical, etc)",
    "sentiment": "The sentiment expressed in the article in one word(e.g., positive, negative, neutral)",
    "tweet": "Summarize this article in a single, impactful sentence that is both informative and tweetable within 240 characters",
    "key_topics": ["A list of key topics or subjects covered in the article. Each topic should have up to 2 words. Pick up to 6 most relevant topics"],
    }}

Please provide your response in the specified JSON format.
    """
    summary_instructions = """Create an accurate detailed summary of the article, written as a concise, standalone article, proportional to the original content's length and complexity. 
    It should naturally weave in the background, key individuals, firms, or entities, important concepts, and significant data points from the original content. 
    The summary should use an active voice and flow as if it's an original piece, providing a clear, engaging overview of the main points. 
    Aim for a style that mirrors the natural storytelling of the original, and use paragraphs and bullets as needed for seperation."""
    
    if type == "inference":
        return inference_instructions
    else:
        return summary_instructions

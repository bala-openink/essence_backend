import boto3
import time

from boto3.dynamodb.conditions import Key
# from transformers import pipeline

from openai import OpenAI

from services import audio_processor
from services import util
from lib import db, log
import config

lambda_client = boto3.client("lambda")
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("AudioChunksStatus")  # DynamoDB table to track status

client = OpenAI(
    # This is the default and can be omitted
    api_key=util.get_secret("OPENAI_API_KEY")
)


def summarize(text):
    return summarize_with_openai(text)

def summarize_with_openai(text, model="gpt-3.5-turbo", temperature=0.5, max_tokens=500):
    """
    Summarize a given text using OpenAI's GPT model.

    Args:
    - text (str): The text to summarize.
    - model (str): Model ID of the OpenAI GPT model to use.
    - temperature (float): Sampling temperature for the model. Lower values make the output more deterministic.
    - max_tokens (int): Maximum number of tokens to generate in the output.

    Returns:
    - str: The summarized text.
    """

    # instructions = """Summarize the article provided, beginning with a one-line inference and conclusion. 
    # Ensure the summary's length reflects the original article's length and complexity, offering an in-depth and thorough analysis without sacrificing clarity and conciseness. 
    # Accurately convey the author's intended meaning, focusing solely on the content of the text. 
    # Format the summary in a clear paragraph structure, highlighting key individuals, firms, or entities mentioned. Avoid external information"""

    # instructions = """Create a concise, comprehensive summary of the text, starting with a single-line overview that captures the article's essence. 
    # The summary should be proportional to the source's length and complexity, aiming for depth and complexity while maintaining readability.
    # It's crucial to reflect the author's intent accurately, sticking to the provided text for information. 
    # Present the summary in paragraph format for straightforward interpretation, including mentions of significant people, firms, or entities."""

    # TODO - Move instructions to a Database
    # TODO - Have multiple instructions to summarize articles better based on the article genre and the reader
    instructions = """Create an accurate detailed summary of the article, written as a concise, standalone article, proportional to the original content's length and complexity. 
    It should naturally weave in the background, key individuals, firms, or entities, important concepts, and significant data points from the original content. 
    The summary should use an active voice and flow as if it's an original piece, providing a clear, engaging overview of the main points. 
    Aim for a style that mirrors the natural storytelling of the original, and use paragraphs and bullets as needed for seperation."""

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

# def summarize_with_opensource_llm(text, model_name, min_length=200, max_length=400):
#     """
#     Summarizes the given text using the specified LLaMa model.

#     :param text: The text to be summarized.
#     :param model_name: The name of the LLaMa model.
#     :param min_length: Minimum length of the summary.
#     :param max_length: Maximum length of the summary.
#     :return: The summarized text.
#     """
#     # Load the summarization pipeline
#     # summarizer = pipeline("summarization", model=model_name, tokenizer="t5-base", framework="tf")
#     summarizer = pipeline("summarization", model=model_name)
#     # Summarize the text
#     summary = summarizer(
#         text, min_length=min_length, max_length=max_length, do_sample=False
#     )
#     return summary[0]["summary_text"]


# def summarize_text_in_chunks(
#     text, model_name, max_chunk_length=800, summary_max_length=80
# ):
#     """
#     Summarizes the text by splitting it into chunks and summarizing each chunk.

#     :param text: The text to be summarized.
#     :param model: The model to use for summarization.
#     :param max_chunk_length: Maximum length of each text chunk in tokens.
#     :param summary_max_length: Maximum length of the summary for each chunk.
#     :return: The summarized text.
#     """
#     # Initialize the summarization pipeline
#     summarizer = pipeline("summarization", model=model_name)

#     # Split the text into chunks
#     words = text.split()
#     chunks = [
#         " ".join(words[i : i + max_chunk_length])
#         for i in range(0, len(words), max_chunk_length)
#     ]

#     # Summarize each chunk and combine
#     summarized_chunks = [
#         summarizer(chunk, max_length=summary_max_length)[0]["summary_text"]
#         for chunk in chunks
#     ]
#     final_summary = " ".join(summarized_chunks)

#     return final_summary



def process_transcript(user_id, id, clean_url, transcript, localMode=True):  
    if(transcript):
        # summarize the transcript
        text_summary = summarize(transcript)
        print(f"Final text summary :: {text_summary}")
        # convert text to audio
        audio_file_url, audio_file_local = audio_processor.text_to_audio_polly(
            id, text_summary
        )

        # persist the summary output
        item = {
            "user_id": user_id or config.DEFAULT_USERNAME,
            "id": id,
            "url": clean_url,
            "transcript": transcript,
            "text_summary": text_summary,
            "audio_summary_url": audio_file_url,
            "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        db.get_summary_table().add(item)

        return item
    else:
        raise Exception(f"Error in processing the summary for {id}. Transcript could not be extracted")


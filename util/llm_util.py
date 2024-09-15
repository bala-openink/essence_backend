import os
from openai import OpenAI
import json
from services import util
from lib.log import logger


client = OpenAI(
    # This is the default and can be omitted
    api_key=util.get_secret("OPENAI_API_KEY")
)

def summarize_text_and_extract_categories(text):
    instructions = f"""
You are a helpful assistant specializing in summarizing articles. Create an accurate detailed summary of the article, written as a concise, standalone article, in 2 different lengths:
1. In 50 words.
2. In 200 words.
Also, extract upto top 3 categories that the article belongs to.

Provide your response in JSON format with the following structure:
{{
    "summary_50": "...",
    "summary_200": "...",
    "categories": ["category1", "category2", ...]
}}
"""
    response = chat_with_openai(text, instructions)

    # Parse the JSON response
    if response:
        try:
            summaries_and_categories = json.loads(response)
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from OpenAI response.")
            summaries_and_categories = {
            "summary_50": "",
            "summary_200": "",
                "categories": []
            }
        return summaries_and_categories
    else:
        return None


def chat_with_openai(text, instructions, model="gpt-4o-mini", temperature=0.5, max_tokens=4000):
    try:
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
    except Exception as e:
        logger.error(f"Error during OpenAI API call: {e}")
        return ""  # Return an empty string or handle as needed

    response = response.choices[0].message.content.strip()
    logger.info(f"Response :: {response}")
    return response

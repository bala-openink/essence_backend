import os
from services.openai_service import openai_service
import json
from services import utilities
from lib.log import logger
import numpy as np


def summarize_text_and_extract_categories(text):
    instructions = f"""
You are a helpful assistant specializing in summarizing articles. Create an accurate detailed summary of the article, written as a concise, standalone article, in 2 different lengths:
1. In 50 words.
2. In 200 words.
Also, extract upto top 3 categories that the article belongs to. Try and use the categories from the below list as much as possible. Where its not possible, add the category that best describes the article.
Category list: Fashion, Grocery, Electronics, Home Goods, Beauty, Wellness, Sports, Toys, Media, Auto/Industrial, Pet Care, Luxury, Digital Marketing, Social Media, E-commerce, Platforms, Retail Tech, Supply Chain, Fintech, Customer Experience, Sustainable Retail, Business Strategy, Consumer Trends, Omnichannel, Store Operations, Data Analytics, Startups, Regulations, Mergers/Acquisitions, Global Trade, Packaging, Cybersecurity, AI/ML, AR/VR, Workforce, Loyalty Programs

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
            # Convert categories to lowercase
            summaries_and_categories['categories'] = [category.lower() for category in summaries_and_categories['categories']]
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
        response = openai_service.client.chat.completions.create(
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
    logger.debug(f"Response :: {response}")
    return response

def get_embedding(text, model="text-embedding-3-small"):
    try:
        text = text.replace("\n", " ")
        response = openai_service.client.embeddings.create(input=[text], model=model)
        embedding = response.data[0].embedding
        return np.array(embedding)
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        return np.array([])

def get_embedding_normalized(text, model="text-embedding-3-small"):
    embedding = get_embedding(text, model)
    embedding_array = np.array(embedding)
    if np.all(embedding_array == 0):
        return embedding_array
    return embedding_array / np.linalg.norm(embedding_array)

def convert_preferences_to_json(text):

    instructions = """
        Your goal is to read the user's news preferences provided below, understand them and convert them into a JSON object:

        Here are the instructions
        - Analyze the user's input to extract the dimensions and their corresponding values.
        Identify various dimensions mentioned by the user (e.g., "Companies", "Topics", "Geographies", "Industries", etc.).
        For Each Dimension, extract the values, exclude_values and priority_order.
        - values: A list of relevant items specified in the user's preferences.
        - exclude_values: A list of items the user wants to exclude, if they have explicitly mentioned to exclude.
        - priority_order: A boolean indicating whether the order of the items in "values" reflects their priority (true) or not (false).

        Using this, populate the JSON object with the provided structure below, ensuring it accurately reflects the user's preferences, including any priorities or exclusions.
        - Respond with a valid JSON object only, without any additional text or explanations.

        Desired JSON Structure:
        {
            "DimensionName1": {
                "values": ["Value1", "Value2", "Value3"],
                "exclude_values": ["ExcludeValue1", "ExcludeValue2"],
                "priority_order": true
            },
            "DimensionName2": {
                "values": ["ValueA", "ValueB"],
                "exclude_values": [],
                "priority_order": false
            }
            // Add more dimensions as identified
        }
    """    

    response = chat_with_openai(text, instructions)
    logger.debug(f"convert_preferences_to_json >> Response :: {response}")
    # Check if the response is valid JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from OpenAI response.")
        return None

def process_user_intent(transcribed_text):
    instructions = """
    Analyze the user's input and determine their intent. Map it to one of the following actions if applicable:
    - skip: User wants to move to the next news item
    - previous: User wants to move to the previous news item
    - bookmark: User wants to save the current news item
    - deepdive: User wants more information on the current topic

    If the intent matches one of these actions, return the action name. If it's unclear or doesn't match, return "unclear".

    Provide your response in JSON format with the following structure:
    {
        "intent": "skip/previous/bookmark/deepdive/unclear",
        "confidence": 0.0 to 1.0,
        "action": "frontend" for skip and deepdive, "backend" for bookmark, "none" for unclear,
        "response": "A brief natural language response to the user's input in as few words as possible"
    }
    """
    
    response = chat_with_openai(transcribed_text, instructions)
    
    try:
        result = json.loads(response)
        logger.info(f"process_user_intent >> Response :: {result}")
        return result["intent"], result["action"], result["response"]
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from OpenAI response in process_user_intent.")
        return "unclear", "none", "I'm sorry, I didn't understand that. Could you please try again?"

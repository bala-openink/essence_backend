import os
from services.openai_service import openai_service
import json
from services import utilities
from lib.log import logger
import numpy as np
import config



def summarize_text_and_extract_categories(text):
    instructions = f"""
You are a helpful assistant specializing in analysing and summarizing articles. 
I will be providing the transcript of a news article.
I would like you to do the following:
1. Create an accurate detailed summary of the article, written as a concise, standalone article in 50 words.
2. Create an accurate detailed summary of the article, written as a concise, standalone article in 200 words.
3. Extract upto top 3 categories that the article belongs to. Try and use the categories from the below list as much as possible. Where its not possible, add the category that best describes the article.
    Category list: Fashion, Grocery, Electronics, Home Goods, Beauty, Wellness, Sports, Toys, Media, Auto/Industrial, Pet Care, Luxury, Digital Marketing, Social Media, E-commerce, Platforms, Retail Tech, Supply Chain, Fintech, Customer Experience, Sustainable Retail, Business Strategy, Consumer Trends, Omnichannel, Store Operations, Data Analytics, Startups, Regulations, Mergers/Acquisitions, Global Trade, Packaging, Cybersecurity, AI/ML, AR/VR, Workforce, Loyalty Programs
4. Extract the most relevant function from this list, that this article will be most relevant to. {config.RETAIL_FUNCTIONS}
5. Extract the most relevant industry from this list, that this article will be most relevant to. {config.RETAIL_INDUSTRIES}
6. Determine if the text is a valid single news item. A valid news item should be a coherent article with a clear topic, not a collection of unrelated news, an advertisement, or a notification. Update the value of "single_news_item" to true if it is a valid news item, otherwise false.
7. Identify the country where the news is happening or applicable to, and update the "region" field.
8. Create an appropriate title for the article in a few words in English.

Provide your response in JSON format with the following structure:
{{
    "summary_50": "...",
    "summary_200": "...",   
    "categories": ["category1", "category2", ...],
    "function": "function that this article will be most relevant to",
    "industry": "industry that this article will be most relevant to",
    "single_news_item": true or false,
    "region": "country where the news is happening or applicable to",
    "english_title": "English title of the article"
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
            "categories": [],
            "importance_score": 0,
            "single_news_item": False
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

def get_embedding_normalized(article, model="text-embedding-3-small"):
    if not article:
        return np.array([])
    
    embedding = get_embedding_with_weights(article.get("summary_200"), article.get("region"), article.get("categories"),
                                            article.get("industry"), article.get("function"), model)
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

def get_embedding_with_weights(text, region=None, categories=None, industry=None, function=None, model="text-embedding-3-small"):
    try:
        # Get separate embeddings for each component
        content_embedding = get_base_embedding(text, model)
        
        # Initialize weights (these could be tuned)
        content_weight = 0.5
        region_weight = 0.1
        industry_weight = 0.2
        function_weight = 0.1
        category_weight = 0.1
        
        final_embedding = content_embedding * content_weight
        
        if region:
            region_embedding = get_base_embedding(region, model)
            final_embedding += region_embedding * region_weight
            
        if categories:
            # Get embedding for each category separately
            category_embeddings = [get_base_embedding(cat, model) for cat in categories]
            avg_category_embedding = np.mean(category_embeddings, axis=0)
            final_embedding += avg_category_embedding * category_weight
        
        if industry:
            industry_embedding = get_base_embedding(industry, model)
            final_embedding += industry_embedding * industry_weight
            
        if function:
            function_embedding = get_base_embedding(function, model)
            final_embedding += function_embedding * function_weight
            
        # Normalize the final embedding
        return final_embedding / np.linalg.norm(final_embedding)
    except Exception as e:
        logger.error(f"Error in weighted embedding generation: {str(e)}")
        return np.array([])

def get_base_embedding(text, model):
    try:
        response = openai_service.client.embeddings.create(
            input=[text.replace("\n", " ")], 
            model=model
        )
        return np.array(response.data[0].embedding)
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        return np.array([])
    

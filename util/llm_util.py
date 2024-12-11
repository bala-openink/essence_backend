import os
from services.openai_service import openai_service
import json
from services import utilities
from lib.log import logger
import numpy as np
import config
import time
import constants


def summarize_text_and_extract_categories(text, model=constants.DEFAULT_MODEL):
    instructions = f"""
You are a helpful assistant specializing in analysing and summarizing articles. 
I will be providing the transcript of a news article.
I would like you to do the following:
1. Create a comprehensive 50-word summary that captures key details, including relevant companies, data points, and business impact. Write it as a standalone article in active voice.
2. Create a detailed 200-word summary that captures the context, key entities, important concepts, and significant data points. Write it as a cohesive standalone article in active voice.
3. Extract upto top 3 categories that the article belongs to. Try and use the categories from the below list as much as possible. Where its not possible, add the category that best describes the article.
    Category list: Fashion, Grocery, Electronics, Home Goods, Beauty, Wellness, Sports, Toys, Media, Auto/Industrial, Pet Care, Luxury, Digital Marketing, Social Media, E-commerce, Platforms, Retail Tech, Supply Chain, Fintech, Customer Experience, Sustainable Retail, Business Strategy, Consumer Trends, Omnichannel, Store Operations, Data Analytics, Startups, Regulations, Mergers/Acquisitions, Global Trade, Packaging, Cybersecurity, AI/ML, AR/VR, Workforce, Loyalty Programs
4. Extract the most relevant function from this list, that this article will be most relevant to. {config.RETAIL_FUNCTIONS}
5. Extract the most relevant industry from this list, that this article will be most relevant to. {config.RETAIL_INDUSTRIES}
6. Determine if the text is a valid single news item. A valid news item should be a coherent article with a clear topic. Following are invalid news items: a collection of unrelated news, an advertisement, or javascript required messages or any other notification messages. Update the value of "single_news_item" to true if it is a valid news item, otherwise false.
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
    response = chat_with_openai(text, instructions, model)

    # Parse the JSON response
    if response:
        return extract_json_from_llm_response(response)
    else:
        return None


def chat_with_openai(text, instructions, model=constants.DEFAULT_MODEL, temperature=0.5, max_tokens=4000):
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

    if response:
        return extract_json_from_llm_response(response)
    else:
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
    
    if response:
        result = extract_json_from_llm_response(response)
        if result:
            logger.info(f"process_user_intent >> Response :: {result}")
            return result["intent"], result["action"], result["response"]
    
    return "unclear", "none", "I'm sorry, I didn't understand that. Could you please try again?"

    
def rank_articles_by_importance(articles):
    start_time = time.time()
    logger.debug(f"rank_articles_by_importance :: Ranking {len(articles)} articles by importance")
    
    # Format articles and estimate tokens
    formatted_articles = [
        f"ID: {article['id']}\nTitle: {article.get('title', 'No title')}\n"
        f"Summary: {article.get('summary_200', 'No summary')}"
        for article in articles
    ]
    
    # Debug log article IDs and titles
    logger.debug("Articles to be ranked:")
    for article in articles:
        logger.debug(f"ID: {article['id']} - Title: {article.get('title', 'No title')}")
    # Estimate tokens for each article
    token_estimates = [estimate_tokens(article) for article in formatted_articles]
    
    articles_text = "\n\n".join(formatted_articles)
    total_estimated_tokens = estimate_tokens(articles_text)
    
    logger.debug(f"Token estimation:")
    logger.debug(f"Total estimated tokens: {total_estimated_tokens}")
    logger.debug(f"Average tokens per article: {sum(token_estimates)/len(token_estimates):.2f}")
    logger.debug(f"Max tokens in single article: {max(token_estimates)}")
    logger.debug(f"Total text length: {len(articles_text)} characters")

    # Prepare prompt for importance ranking
    prompt = """
    You are an expert news analyst. Review these articles and rank them by importance among each other
    on a scale of 1-100, considering:
    - Impact - economic, social and business impact
    - Size of the brand/company/organization/individual involved
    - Industry disruption potential
    - Scale (financial amounts, reach)
    - Relevance to key stakeholders
    - Timeliness and urgency
    Ensure all {len(articles)} articles are ranked on the scale of 1-100 without missing any.
    Return a JSON object mapping article IDs to their importance scores (1-100), in this format:
    {
        "article_id1": 75,
        "article_id2": 23
    }
    """

    # Get rankings from LLM
    response = chat_with_openai(articles_text, prompt, model=constants.DEFAULT_MODEL, max_tokens=10000)
    logger.debug(f"rank_articles_by_importance >>>> :: Response :: {response}")
    rankings = extract_json_from_llm_response(response)
    logger.debug(f"rank_articles_by_importance :: Rankings :: {rankings}")
    if isinstance(rankings, dict):
        article_scores = [
            {"id": article_id, "importance_score": score}
            for article_id, score in rankings.items()
        ]
        return article_scores

    logger.debug(f"rank_articles_by_importance :: Ranked {len(rankings)} articles. Time taken: {time.time() - start_time} seconds")
    return rankings

def extract_json_from_llm_response(response_text):
    """
    Extract valid JSON from LLM response by removing common prefixes/suffixes.
    Returns the parsed JSON object or None if parsing fails.
    """
    if not response_text:
        return None
    try:
        # First try parsing the raw response
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        # Remove common prefixes
        cleaned = response_text.strip()
        for prefix in ['```json', '```']:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        # Remove common suffixes
        for suffix in ['```', "'", '"']:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
                break
        
        cleaned = cleaned.strip()
        
        # Check if it's meant to be an array
        if cleaned.startswith('['):
            if not cleaned.endswith(']'):
                cleaned = cleaned + ']'
        else:  # Assume it's meant to be an object
            if not cleaned.startswith('{'):
                cleaned = '{' + cleaned
            if not cleaned.endswith('}'):
                cleaned = cleaned + '}'

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON after cleaning: {cleaned}")
            return None

def rank_articles_by_importance_batched(articles, batch_size=200):
    """
    Ranks articles by importance, handling large sets by breaking them into batches
    and performing a final re-ranking of top articles from each batch.
    """
    start_time = time.time()
    logger.info(f"rank_articles_by_importance_batched :: Ranking {len(articles)} articles by importance")
    
    # If articles are fewer than batch_size, use the original method
    if len(articles) <= batch_size:
        return rank_articles_by_importance(articles)
    
    # Split articles into batches
    batches = [articles[i:i + batch_size] for i in range(0, len(articles), batch_size)]
    batch_rankings = []
    
    # Rank each batch
    for i, batch in enumerate(batches):
        logger.info(f"Processing batch {i+1}/{len(batches)} with {len(batch)} articles")
        batch_result = rank_articles_by_importance(batch)
        if batch_result:
            batch_rankings.extend(batch_result)
    
    # Sort all rankings by importance score
    sorted_rankings = sorted(batch_rankings, key=lambda x: x['importance_score'], reverse=True)
    
    # Take top 200 articles for final re-ranking
    top_articles = []
    seen_ids = set()
    for ranking in sorted_rankings:
        article = next((a for a in articles if a['id'] == ranking['id']), None)
        if article and article['id'] not in seen_ids:
            top_articles.append(article)
            seen_ids.add(article['id'])
            if len(top_articles) >= batch_size:
                break
    
    # Perform final ranking on top articles
    final_rankings = rank_articles_by_importance(top_articles) if top_articles else []
    
    # Append remaining articles with their original scores
    final_rankings_dict = {r['id']: r['importance_score'] for r in final_rankings}
    for ranking in sorted_rankings:
        if ranking['id'] not in final_rankings_dict:
            final_rankings.append(ranking)
    
    logger.info(f"rank_articles_by_importance_batched :: Completed ranking. Time taken: {time.time() - start_time} seconds")
    return final_rankings

def estimate_tokens(text):
    """Estimate the number of tokens in a text using GPT-2 tokenizer rules.
    This is a rough approximation - actual OpenAI tokens may vary."""
    # Simple estimation rules
    # 1. ~4 characters per token is a common rough estimate
    # 2. Each punctuation mark and space typically counts as a token
    # 3. Numbers and special characters may count as multiple tokens
    
    base_estimate = len(text) / 4
    # Add extra tokens for newlines and punctuation
    extra_tokens = text.count('\n') + text.count('.') + text.count(',') + text.count('!') + text.count('?')
    return int(base_estimate + extra_tokens)

def generate_image_from_text(text, region="UK", size="1024x1024", style="natural", quality="standard"):
    """
    Generate an image from text using DALL-E 3.
    
    Args:
        text (str): The text description to generate an image from
        size (str): Size of the image ("1024x1024", "1792x1024", or "1024x1792")
        style (str): "natural" or "vivid"
        quality (str): "standard" or "hd"
    
    Returns:
        dict: Contains 'url' of the generated image and 'revised_prompt' that DALL-E used
        None: If generation fails
    """
    logger.info(f"generate_image_from_text :: Generating image for text: {text}")
    try:
        # Create a more specific prompt for news-style images
        enhanced_prompt = f"""
        Create a professional image for a piece of news:
        Style: Flat vector-style illustration, featuring clean lines, soft gradient backgrounds, and minimalist design. Subtle glowing effects with geometric shapes and a modern, digital aesthetic. Use calming and vibrant colors for a polished and professional look.
        This is set in the region of {region}.
        Avoid people or human figures.
        No signs, markings, words, watermarks or text should be present in the image.
        Here is the news snippet: {text}
        """
        
        response = openai_service.client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size=size,
            quality=quality,
            style=style,
            n=1
        )

        if response and response.data:
            logger.info(f"Generated image url :: {response.data[0].url}")
            return {
                'url': response.data[0].url,
                'revised_prompt': response.data[0].revised_prompt
            }
        
        return None

    except Exception as e:
        logger.error(f"Error during DALL-E image generation: {e}")
        return None


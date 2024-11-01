import csv
import requests
import threading
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import datetime  # Add this import at the top
from dateutil import parser as date_parser
import hashlib  # Add this import at the top
from flask import jsonify
from config import ADMIN_EMAIL, SKIP_EXPENSIVE_OPERATIONS, OPENSEARCH_INDEX
import random
import numpy as np

from services.utilities import extract_transcript, upload_audiostory_to_s3, background_task
from util.llm_util import summarize_text_and_extract_categories
from db import db
from lib.log import logger
from services import podcaster
from models.audio_story_request import AudioStoryRequest
from pydub import AudioSegment
from lib.email_service import send_email
import traceback
from util import llm_util
from util.vector_util import cosine_similarity

# Start the feed processing in a separate thread
def start_feed_processing():
    background_task(parse_feeds)
    return jsonify({"message": "Feed processing started"}), 202

# Remove the CSV reading part and replace it with this function
def get_enabled_feeds():
    feed_table = db.get_feed_table()
    return feed_table.query_enabled_feeds()

# TODO - Add handling for feeds that are not fully processed yet, got errored out in different stages
# Update the parse_feeds function
def parse_feeds():
    try:
        feeds = get_enabled_feeds()
        total_articles = 0
        total_skipped = 0
        error_articles = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for feed in feeds:
                futures.append(executor.submit(parse_feed, feed))
            
            # Wait for all tasks to complete or timeout
            for future in futures:
                try:
                    result = future.result(timeout=300)  # 5 minutes timeout per feed
                    total_articles += result['processed']
                    total_skipped += result['skipped']
                    error_articles.extend(result['errors'])
                except TimeoutError:
                    logger.warning(f"Feed processing timed out for {future}")
                except Exception as e:
                    logger.error(f"Error processing feed: {str(e)}")

        logger.info(f"All feeds processed. Total articles: {total_articles}, Skipped: {total_skipped}, Errors: {len(error_articles)}")
        
        # Process summaries and generate audio after all feeds are processed
        processed_count, deduped_count, error_count = process_summaries_and_generate_audio()
        
        # Send email with processing summary
        send_processing_summary_email(total_articles, total_skipped, error_articles, processed_count, deduped_count, error_count)
    except Exception as e:
        logger.error(f"Error in parse_feeds: {str(e)}")

# Update the parse_feed function
def parse_feed(feed):
    rss_type = feed['rss_type']
    source_name = feed['source_name']
    category = feed['category']
    feed_url = feed['feed_url']
    feed_id = feed['id']

    if rss_type == 'rss.app':
        processed_count, skipped_count, errors = parse_rss_app_feed(source_name, category, feed_url)
    # Add other RSS types here as needed

    # Update the last processed date
    feed_table = db.get_feed_table()
    feed_table.update_last_processed_date(feed_id, datetime.datetime.now(datetime.timezone.utc).isoformat())

    return {'processed': processed_count, 'skipped': skipped_count, 'errors': errors}

# Parses the feed from rss.app
def parse_rss_app_feed(source_name, category, feed_url):
    processed_count = 0
    skipped_count = 0
    errors = []
    response = requests.get(feed_url)
    if response.status_code == 200:
        feed_data = response.json()
        logger.debug("parse_rss_app_feed::feed_data: %s", feed_data)
        items = feed_data.get('items', [])
        for item in items:
            try:
                result = process_feed_item_initial(item, source_name, category)
                if result == 'processed':
                    processed_count += 1
                elif result == 'skipped':
                    skipped_count += 1
            except Exception as e:
                error_msg = f"Error processing item from {feed_url}: {str(e)}"
                logger.error(error_msg)
                errors.append({'url': item.get('url', 'Unknown URL'), 'error': error_msg})
    else:
        error_msg = f"Failed to fetch feed from {feed_url}"
        logger.error(error_msg)
        errors.append({'url': feed_url, 'error': error_msg})
    
    return processed_count, skipped_count, errors

def process_feed_item_initial(item, source_name, category):
    try:
        article_id = hashlib.sha256(item.get('id', '').encode()).hexdigest()
        article = get_or_create_article(article_id, item, source_name, category)
    except Exception as e:
        raise Exception(f"Error creating/retrieving article: {str(e)}")

    if article['processing_status'] == 'audio_summary_generated':
        logger.info(f"Skipping already processed article {article_id}")
        return 'skipped'

    if article['processing_status'] == 'started':
        extract_and_save_transcript(article)
    
    if not SKIP_EXPENSIVE_OPERATIONS:
        if article['processing_status'] == 'transcript_extracted':
            summarize_and_save(article)
    else:
        logger.info(f"Skipping expensive operations for article {article_id}")
        article['processing_status'] = 'skipped_expensive_operations'
        db.get_article_table().addOrUpdate(article)

    logger.info(f"Processed article {article_id}")
    return 'processed'

def get_or_create_article(article_id, item, source_name, category):
    try:
        existing_article = db.get_article(article_id)
        
        if existing_article:
            logger.info(f"Article {article_id} already exists. Current status: {existing_article['processing_status']}")
            return existing_article
        
        # Handle date_published
        date_published = parse_and_format_date(item.get('date_published'))
        
        # Update date_published to current time if it's too old
        if _is_older_than_few_years(date_published):
            date_published = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        new_article = {
            'id': article_id,
            'title': item.get('title'),
            'url': item.get('url'),
            'image': item.get('image'),
            'date_published': date_published,
            'rss_summary': item.get('content_text'),
            'source_name': source_name,
            'type': category,
            'processing_status': 'started'
        }
        db.add_or_update_article(new_article)
        logger.info(f"Created new article {article_id}")
        return new_article
    except Exception as e:
        logger.error(f"Error in get_or_create_article: {str(e)}")
        raise

def parse_and_format_date(date_string):
    if not date_string:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    try:
        # Parse the date_string into a datetime object
        parsed_date = date_parser.parse(date_string)
        
        # If the parsed date doesn't have timezone info, assume it's UTC
        if not parsed_date.tzinfo:
            parsed_date = parsed_date.replace(tzinfo=datetime.timezone.utc)
        
        # Convert to UTC if it's not already
        utc_date = parsed_date.astimezone(datetime.timezone.utc)
        
        # Format as ISO 8601 string
        return utc_date.isoformat()
    except ValueError:
        # If parsing fails, use the current UTC time
        logger.warning(f"Failed to parse date: {date_string}. Using current UTC time.")
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

def _is_older_than_few_years(date_string, years=10):
    try:
        date = datetime.datetime.fromisoformat(date_string)
        current_date = datetime.datetime.now(datetime.timezone.utc)
        return (current_date - date).days > (years * 365)
    except ValueError:
        logger.error(f"Invalid date format: {date_string}")
        return False

def extract_and_save_transcript(article):
    try:
        url = article.get('url')
        if not url:
            raise ValueError(f"No URL found for article {article['id']}")
        
        text_content = extract_transcript(url)
        if not text_content:
            raise ValueError(f"Failed to extract transcript for article {article['id']}")

        # remove newlines and extra whitespace
        text_content = text_content.replace('\n', ' ').strip()
        article['full_text'] = text_content
        article['processing_status'] = 'transcript_extracted'
        db.add_or_update_article(article)
        logger.info(f"Extracted transcript for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in extract_and_save_transcript: {str(e)}")
        raise

def summarize_and_save(article):
    try:
        text_content = article.get('full_text')
        if not text_content:
            raise ValueError(f"No full text found for article {article['id']}")
        
        summaries_and_categories = summarize_text_and_extract_categories(text_content)
        if not summaries_and_categories:
            raise ValueError(f"Failed to summarize article {article['id']}")
        
        article['summary_50'] = summaries_and_categories.get('summary_50')
        article['summary_200'] = summaries_and_categories.get('summary_200')
        article['categories'] = summaries_and_categories.get('categories')
        article['processing_status'] = 'summaries_extracted'
        
        # Vectorize the summary and persist in OpenSearch
        summary_vector = llm_util.get_embedding_normalized(article['summary_200'])
        article['summary_vector'] = summary_vector
        
        db.add_or_update_article(article)
        logger.info(f"Summarized and extracted categories for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in summarize_and_save: {str(e)}")
        raise

def process_summaries_and_generate_audio():
    articles_to_process = db.query_articles_by_status('summaries_extracted', limit=1000)
    
    logger.info(f"Found {len(articles_to_process)} articles with 'summaries_extracted'")
    
    # Perform deduplication
    deduplicated_articles = deduplicate_articles(articles_to_process)
    
    error_count = 0
    previous_article = None
    for article in deduplicated_articles:
        try:
            generate_and_save_audio_summary(article, previous_article)
            previous_article = article
        except Exception as e:
            error_count += 1
            logger.error(f"Error generating audio summary for article {article['id']}: {str(e)}")
            previous_article = None
    
    return len(articles_to_process), len(deduplicated_articles), error_count

def deduplicate_articles(articles):
    if not articles:
        return []

    logger.info(f"Starting deduplication process with {len(articles)} articles")

    vectors = np.array([article['summary_vector'] for article in articles])
    similarity_matrix = cosine_similarity(vectors)
    
    deduplicated_indices = set()
    removed_count = 0

    for i in range(len(articles)):
        if i not in deduplicated_indices:
            deduplicated_indices.add(i)
            for j in range(i + 1, len(articles)):
                if similarity_matrix[i][j] > 0.80:  # Adjust this threshold as needed
                    logger.debug(f"Duplicate found: {articles[i]['title']} and {articles[j]['title']} with similarity {similarity_matrix[i][j]:.4f}")
                    # Keep the more recent article
                    if articles[i]['date_published'] < articles[j]['date_published']:
                        deduplicated_indices.remove(i)
                        deduplicated_indices.add(j)
                        removed_count += 1
                        logger.debug(f"Removed older article: {articles[i]['id']}")
                        break
                    else:
                        removed_count += 1
                        logger.debug(f"Removed newer duplicate: {articles[j]['id']}")

    deduplicated_articles = [articles[i] for i in deduplicated_indices]
    
    logger.info(f"Deduplication complete. Removed {removed_count} articles. {len(deduplicated_articles)} articles remaining.")

    return deduplicated_articles

def generate_and_save_audio_summary(article, previous_article=None):
    try:
        # Randomly set two_speakers to True or False
        two_speakers = random.random() < 0.3

        # TODO - No user specific customizations are happening now. 
        audio_request = AudioStoryRequest(
            id=article['id'],
            text_summary=article['summary_200'],
            url=article['url'],
            length="short",
            language="en",
            region="UK",
            two_speakers=two_speakers,
            add_background=False,
            user_name=None,
            previous_article=previous_article['summary_50'] if previous_article else None
        )
        audio_summary = podcaster.generate_audio_story(audio_request)
        
        # Build the streaming response object and upload to S3
        output = BytesIO()
        audio_summary.export(output, format="mp3")

        s3_url = upload_audiostory_to_s3(audio_request, output)
        
        article['audio_summary'] = s3_url
        article['processing_status'] = 'audio_summary_generated'
        db.add_or_update_article(article)
        logger.info(f"Generated and saved audio summary for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in generate_and_save_audio_summary: {str(e)}")
        db.add_or_update_article(article)
        raise

def send_processing_summary_email(total_articles, total_skipped, error_articles, processed_count, deduped_count, error_count):
    subject = "Essence Feed Processing Summary"
    body = f"""
        Feed processing completed.

        Summary Extraction:
        Total articles processed: {total_articles}
        Total articles skipped: {total_skipped}
        Total articles with errors: {len(error_articles)}

        Audio Summary Generation:
        Total articles processed: {processed_count}
        Total articles after deduplication: {deduped_count}
        Total articles with errors: {error_count}

        Articles with errors:
        """
    
    for article in error_articles:
        body += f"- URL: {article['url']}\n  Error: {article['error']}\n"

    send_email(ADMIN_EMAIL, subject, body)

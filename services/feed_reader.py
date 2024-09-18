import csv
import requests
import threading
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import datetime  # Add this import at the top
from dateutil import parser as date_parser
import hashlib  # Add this import at the top
from flask import jsonify

from services.utilities import extract_transcript, upload_audiostory_to_s3
from util.llm_util import summarize_text_and_extract_categories
from lib import db
from lib.log import logger
from services import podcaster
from models import AudioStoryRequest
from pydub import AudioSegment


# Start the feed processing in a separate thread
def start_feed_processing():
    thread = threading.Thread(target=parse_feeds)
    thread.start()
    return jsonify({"message": "Feed processing started"}), 202


# TODO - Add handling for feeds that are not fully processed yet, got errored out in different stages
# Entry point for parsing all the feeds. Parses the feeds in parallel
def parse_feeds():
    try:
        with open('feeds.csv', 'r') as csvfile:
            reader = csv.reader(csvfile)
            next(reader)  # Skip the first line
            feeds = [row for row in reader if not row[0].startswith('#')]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for row in feeds:
                rss_type, source_name, category, feed_url = row
                futures.append(executor.submit(parse_feed, rss_type, source_name, category, feed_url))
            
            # Wait for all tasks to complete or timeout
            for future in futures:
                try:
                    future.result(timeout=300)  # 5 minutes timeout per feed
                except TimeoutError:
                    logger.warning(f"Feed processing timed out for {future}")
                except Exception as e:
                    logger.error(f"Error processing feed: {str(e)}")

        logger.info("All feeds processed")
    except Exception as e:
        logger.error(f"Error in parse_feeds: {str(e)}")

# Parses the feed based on the RSS type
# TODO - Add parsing for other RSS types like feedspot, feed43, etc.
def parse_feed(rss_type, source_name, category, feed_url):
    if rss_type == 'rss.app':
        parse_rss_app_feed(source_name, category, feed_url)
    # Add other RSS types here as needed

# Parses the feed from rss.app
def parse_rss_app_feed(source_name, category, feed_url):
    response = requests.get(feed_url)
    if response.status_code == 200:
        feed_data = response.json()
        logger.info("parse_rss_app_feed::feed_data: %s", feed_data)  # Changed to logger.info
        items = feed_data.get('items', [])
        for item in items:
            process_feed_item(item, source_name, category)
    else:
        logger.error("Failed to fetch feed from %s", feed_url)

def process_feed_item(item, source_name, category):
    try:
        article_id = hashlib.sha256(item.get('id', '').encode()).hexdigest()
        article = get_or_create_article(article_id, item, source_name, category)
    except Exception as e:
        logger.error(f"Error creating/retrieving article: {str(e)}")
        return

    try:
        if article['processing_status'] == 'started':
            extract_and_save_transcript(article)
    except Exception as e:
        logger.error(f"Error extracting transcript for article {article_id}: {str(e)}")
        return

    try:
        if article['processing_status'] == 'transcript_extracted':
            summarize_and_save(article)
    except Exception as e:
        logger.error(f"Error summarizing article {article_id}: {str(e)}")
        return

    try:
        if article['processing_status'] == 'summaries_extracted':
            generate_and_save_audio_summary(article)
    except Exception as e:
        logger.error(f"Error generating audio summary for article {article_id}: {str(e)}")
        return

    logger.info(f"Successfully processed article {article_id}")

def get_or_create_article(article_id, item, source_name, category):
    try:
        article_table = db.get_article_table()
        existing_article = article_table.get(article_id)
        
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
        article_table.addOrUpdate(new_article)
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
        
        article['full_text'] = text_content
        article['processing_status'] = 'transcript_extracted'
        db.get_article_table().addOrUpdate(article)
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
        db.get_article_table().addOrUpdate(article)
        logger.info(f"Summarized and extracted categories for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in summarize_and_save: {str(e)}")
        raise

def generate_and_save_audio_summary(article):
    try:
        # TODO - No user specific customizations are happening now. 
        audio_request = AudioStoryRequest(
            id=article['id'],
            text_summary=article['summary_200'],
            url=article['url'],
            length="short",
            language="en",
            region="UK",
            two_speakers=True,
            add_background=True,
            user_name=None
        )
        audio_summary = podcaster.generate_audio_story(audio_request)
        
        # Build the streaming response object and upload to S3
        output = BytesIO()
        audio_summary.export(output, format="mp3")

        s3_url = upload_audiostory_to_s3(audio_request, output)
        
        article['audio_summary'] = s3_url
        article['processing_status'] = 'audio_summary_generated'
        db.get_article_table().addOrUpdate(article)
        logger.info(f"Generated and saved audio summary for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in generate_and_save_audio_summary: {str(e)}")
        db.get_article_table().addOrUpdate(article)
        raise


import requests
from io import BytesIO
import datetime  # Add this import at the top
import hashlib  # Add this import at the top
from config import ADMIN_EMAIL, SKIP_EXPENSIVE_OPERATIONS
import random

from services import utilities
from util import llm_util, date_util

from lib.log import logger
from services import podcaster
from models.audio_story_request import AudioStoryRequest
from lib.email_service import send_email
from util import llm_util
from util import vector_util
import config
from util import string_util
from services import user_feed
from util import feed_util
from db.factory import db_factory

stage = config.STAGE

user_feed_service = user_feed.UserFeedService()

# Initialize repositories
feed_repo = db_factory.get_generic_repository('feed')
feed_batch_repo = db_factory.get_feed_batch_repository()
article_repo = db_factory.get_article_repository()

def get_enabled_feeds():
    """Get all enabled feeds"""
    return feed_repo.list(status='enabled')

def parse_feeds():
    '''
    Parse all enabled feeds in batches.
    Processing involves 3 stages.
    Stage1: 
    Extracting transcripts, summaries, categories and other metadata.
    No offset, limit tracker. Get all enabled feeds and fetch the predefined number of articles from each feed.
    Batching by feed. Trigger a background task for each feed.
    Stage2: 
    Deduplication and creating audio summaries.
    Batching by number of articles based on lambda timeout value. Trigger a background task for each batch
    Stage3:
    Creating user feeds.
    Batching by group of users. Trigger a background task for each batch
    '''
    try:
        feeds = get_enabled_feeds()
        batch_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
        
        # Create a batch record to track overall progress
        batch_record = {
            'id': batch_id,
            'total_feeds': len(feeds),
            'completed_feeds': 0,
            'start_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'status': 'in_progress',
            'results': {
                'total_articles': 0,
                'total_skipped': 0,
                'error_articles': []
            }
        }
        feed_batch_repo.create_batch(batch_record)

        # Start a background task for each feed
        for feed in feeds:
            try:
                # Include batch_id in the background task parameters
                utilities.background_task('services.feed_reader.process_stage1', feed, batch_id)
                logger.info(f"Started background task for feed {feed['id']} in batch {batch_id}")
            except Exception as e:
                error_msg = f"Error starting background task for feed {feed['id']}: {str(e)}"
                logger.error(error_msg)
                update_batch_status(batch_id, "stage1", error_msg=error_msg)

        logger.info(f"All feed processing tasks initiated for batch {batch_id}")

        return {
            'message': f"Initiated processing for {len(feeds)} feeds",
            'batch_id': batch_id
        }

    except Exception as e:
        logger.error(f"Error in parse_feeds: {str(e)}")

# Update the parse_feed function
def process_stage1(feed, batch_id=None):
    try:
        rss_type = feed.get('rss_type')
        source_name = feed.get('source_name')
        category = feed.get('category')
        feed_url = feed.get('feed_url')
        feed_id = feed.get('id')

        if rss_type == 'rss.app':
            processed_count, skipped_count, errors = process_stage1_rssapp(source_name, category, feed_url)

        # Update the last processed date
        feed['last_processed_date'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        feed_repo.update(feed)

        result = {
            'processed': processed_count, 
            'skipped': skipped_count, 
            'errors': errors,
            'feed_id': feed_id
        }

        # Update batch with success result
        update_batch_status(batch_id, stage="stage1", result=result, feed=feed)
        
        # Check if all feeds are processed
        batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
        if batch and batch['completed_feeds'] >= batch['total_feeds']:
            # Mark stage1 as complete
            feed_batch_repo.mark_stage_complete(
                batch_id=batch_id,
                stage='stage1',
                end_time=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            
            # Send email with processing summary
            if batch:
                send_processing_summary_email("stage1",
                    batch['results']['total_articles'],
                    batch['results']['total_skipped'],
                    batch['results']['error_articles']
                )

            # Trigger stage2
            utilities.background_task('services.feed_reader.process_stage2', batch_id)
        
        return

    except Exception as e:
        error_msg = f"Error processing feed {feed.get('id', 'unknown')}: {str(e)}"
        logger.error(error_msg)
        update_batch_status(batch_id, "stage1", error_msg=error_msg, feed=feed)
        return
    
def update_batch_status(batch_id, stage, result=None, error_msg=None, feed=None):
    """
    Update the batch record with processing results for different stages.
    
    Args:
        batch_id (str): The ID of the batch
        stage (str): Processing stage ('stage1', 'stage2', 'stage3')
        result (dict, optional): Success result containing processed/skipped counts
        error_msg (str, optional): Error message if processing failed
        feed (dict, optional): Feed being processed (only for stage1)
    """
    try:
        if stage == 'stage1' and not feed:
            raise ValueError("Feed is required for stage1 updates")

        # Prepare error info if there's an error message
        error_info = {}
        if error_msg:
            error_info = {
                'error': error_msg,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            # Add feed details for stage1 errors
            if stage == 'stage1' and feed:
                error_info.update({
                    'feed_id': feed.get('id', 'unknown'),
                    'feed_url': feed.get('feed_url', 'Unknown')
                })

        # Update batch using repository
        success = feed_batch_repo.update_batch_status(
            batch_id=batch_id,
            stage=stage,
            result=result,
            error_msg=error_info
        )

        if success:
            logger.info(f"Updated batch {batch_id} for {stage}")
        else:
            logger.error(f"Failed to update batch {batch_id} for {stage}")
            
    except Exception as e:
        logger.error(f"Error updating batch status for {batch_id}: {str(e)}")

# Parses the feed from rss.app
def process_stage1_rssapp(source_name, category, feed_url):
    processed_count = 0
    skipped_count = 0
    errors = []
    response = requests.get(feed_url)

    if response.status_code == 200:
        feed_data = response.json()
        logger.debug("parse_rss_app_feed::feed_data")
        items = feed_data.get('items', [])

        for item in items:
            try:
                result = process_stage1_feed_item(item, source_name, category)
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

def process_stage1_feed_item(item, source_name, category):
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
        article_repo.addOrUpdate(article)

    logger.info(f"Processed article {article_id}")
    return 'processed'

def get_or_create_article(article_id, item, source_name, category):
    try:
        # Try to get existing article
        existing_article = article_repo.get(article_id)
        
        if existing_article:
            logger.info(f"Article {article_id} already exists. Current status: {existing_article['processing_status']}")
            return existing_article
        
        # Handle date_published
        date_published = date_util.format_date_published(item.get('date_published'))
        
        # Create new article
        new_article = {
            'id': article_id,
            'title': item.get('title'),
            'url': item.get('url'),
            'domain': string_util.extract_domain(item.get('url')) if item.get('url') else None,
            'image': item.get('image'),
            'date_published': date_published,
            'rss_summary': item.get('content_text'),
            'source_name': source_name,
            'type': category,
            'date_created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'processing_status': 'started'
        }
        
        # Add article using repository
        result = article_repo.addOrUpdate(new_article)
        if not result:
            raise Exception(f"Failed to create article {article_id}")
            
        logger.info(f"Created new article {article_id}")
        return new_article
        
    except Exception as e:
        logger.error(f"Error in get_or_create_article: {str(e)}")
        raise


def extract_and_save_transcript(article):
    try:
        url = article.get('url')
        if not url:
            raise ValueError(f"No URL found for article {article['id']}")
        
        text_content = feed_util.extract_transcript(url)
        if not text_content:
            raise ValueError(f"Failed to extract transcript for article {article['id']}")

        # remove newlines and extra whitespace
        text_content = text_content.replace('\n', ' ').strip()
        article['full_text'] = text_content
        article['processing_status'] = 'transcript_extracted'
        article_repo.addOrUpdate(article)
        logger.info(f"Extracted transcript for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in extract_and_save_transcript: {str(e)}")
        raise

def summarize_and_save(article):
    try:
        text_content = article.get('full_text')
        if not text_content:
            raise ValueError(f"No full text found for article {article['id']}")
        
        summaries_and_categories = llm_util.summarize_text_and_extract_categories(text_content)
        if not summaries_and_categories:
            raise ValueError(f"Failed to summarize article {article['id']}")
        
        article['summary_50'] = summaries_and_categories.get('summary_50')
        article['summary_200'] = summaries_and_categories.get('summary_200')
        article['categories'] = summaries_and_categories.get('categories')
        article['function'] = summaries_and_categories.get('function')
        article['industry'] = summaries_and_categories.get('industry')
        article['single_news_item'] = summaries_and_categories.get('single_news_item')
        article['region'] = summaries_and_categories.get('region')

        if summaries_and_categories.get('english_title'):
            article['title'] = summaries_and_categories.get('english_title')

        if(article['single_news_item']):
            article['processing_status'] = 'summaries_extracted'
            # Vectorize the summary and persist in OpenSearch
            summary_vector = llm_util.get_embedding_normalized(article)
            article['summary_vector'] = summary_vector
        else:
            article['processing_status'] = 'discarded_after_summaries_extracted'
        
        article_repo.addOrUpdate(article)
        logger.info(f"Summarized and extracted categories for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in summarize_and_save: {str(e)}")
        raise

def process_stage2(batch_id=None):
    """
    Stage2:
    Deduplication and creating audio summaries.
    Batching by number of articles based on lambda timeout value. Trigger a background task for each batch
    """
    try:
        logger.info(f"Processing batch {batch_id} for stage2")
        batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
        
        if batch:
            articles_to_process = article_repo.query_by_status('summaries_extracted', start_date=batch['start_time'])
        else:   
            articles_to_process = article_repo.query_by_status('summaries_extracted', limit=1000)
        
        logger.info(f"Found {len(articles_to_process)} articles with 'summaries_extracted'")
        
        # Perform deduplication
        duplicate_articles, deduplicated_articles = vector_util.deduplicate_articles(articles_to_process)
        article_repo.bulk_update(duplicate_articles)

        # Start processing first batch
        utilities.background_task('services.feed_reader.generate_audio_summaries_batch', 
                                batch_id, 
                                start_date=batch['start_time'] if batch else None)
        
        logger.info(f"Initiated audio summary generation for stage2 processing for batch {batch_id}")
                
    except Exception as e:
        logger.error(f"Error processing completed batch {batch_id}: {str(e)}")

def generate_audio_summaries_batch(batch_id=None, start_date=None, batch_size=100):
    """
    Process a batch of articles for audio summary generation.
    Will trigger next batch if more articles exist.
    """
    try:
        # Query next batch of articles in summaries_extracted state, till nothing left
        articles_to_process = article_repo.query_by_status('summaries_extracted', 
                                                        start_date=start_date,
                                                        limit=batch_size)
        
        if not articles_to_process:
            logger.info(f"No more articles to process for batch {batch_id}")
            # Mark stage2 as complete            
            feed_batch_repo.mark_stage_complete(
                batch_id=batch_id,
                stage='stage2',
                end_time=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            
            # Send summary email and trigger stage3
            batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
            if batch:
                send_processing_summary_email("stage2",
                    batch.get('stage2', {}).get('processed', 0),
                    batch.get('stage2', {}).get('skipped', 0),
                    batch.get('stage2', {}).get('errors', [])
                )

            # Trigger stage3
            utilities.background_task('services.feed_reader.process_stage3', batch_id)
            return
        
        logger.info(f"Processing batch of {len(articles_to_process)} articles")
        
        processed_count = 0
        error_count = 0
        
        for article in articles_to_process:
            try:
                # Verify article is still in correct state before processing
                current_article = article_repo.get(article['id'])
                if current_article['processing_status'] != 'summaries_extracted':
                    continue
                
                # Update status to prevent other processes from picking it up
                article['processing_status'] = 'generating_audio'
                article_repo.addOrUpdate(article)
                
                generate_and_save_audio_summary(article)
                processed_count += 1
                
            except Exception as e:
                error_msg = f"Error processing article {article['id']}: {str(e)}"
                logger.error(error_msg)
                error_count += 1
                
                # Reset article status and record error
                article['processing_status'] = 'summaries_extracted'
                article_repo.addOrUpdate(article)
                
                update_batch_status(batch_id, "stage2", error_msg=error_msg)

        # Update batch with results
        result = {
            'processed': processed_count,
            'skipped': len(articles_to_process) - processed_count - error_count,
            'errors': error_count
        }
        update_batch_status(batch_id, "stage2", result=result)
        
        # Trigger next batch
        utilities.background_task('services.feed_reader.generate_audio_summaries_batch', 
                                batch_id, 
                                start_date=start_date)
        
    except Exception as e:
        error_msg = f"Error in generate_audio_summaries_batch: {str(e)}"
        logger.error(error_msg)
        update_batch_status(batch_id, "stage2", error_msg=error_msg)
        

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
            add_background=True,
            user_name=None,
            previous_article=previous_article['summary_50'] if previous_article else None
        )
        audio_summary = podcaster.generate_audio_story(audio_request)
        
        # Build the streaming response object and upload to S3
        output = BytesIO()
        audio_summary.export(output, format="mp3")

        s3_url = utilities.upload_audiostory_to_s3(audio_request, output)
        
        article['audio_summary'] = s3_url
        article['processing_status'] = 'audio_summary_generated'
        article_repo.addOrUpdate(article)
        logger.info(f"Generated and saved audio summary for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in generate_and_save_audio_summary: {str(e)}")
        # Reset article status and record error
        article['processing_status'] = 'summaries_extracted'
        article_repo.addOrUpdate(article)

def process_stage3(batch_id=None, user_offset=0, total_users=0, batch_size=10):
    """
    Stage3: Creating user feeds.
    Process a batch of users for feed creation.
    Will trigger next batch if more users exist.
    """
    try:
        # Get next batch of users
        active_users = user_feed_service.get_active_users(offset=user_offset, limit=batch_size)
                
        logger.info(f"Processing batch of {len(active_users)} users (offset: {user_offset}/{total_users})")
        
        # Process the batch of users
        user_feed_service.create_user_feeds_for_articles(active_users, batch_id)
        
        # Trigger next batch
        next_offset = user_offset + batch_size
        if next_offset < total_users:
            utilities.background_task('services.feed_reader.process_stage3', 
                                    batch_id, 
                                    user_offset=next_offset,
                                    total_users=total_users)
        else:
            logger.info(f"No more users to process for batch {batch_id}")
            # Mark stage3 as complete
            feed_batch_repo.mark_stage_complete(
                batch_id=batch_id,
                stage='stage3',
                end_time=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

            # Send final summary email
            batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
            if batch:
                send_processing_summary_email("stage3",
                    batch.get('stage3', {}).get('processed', 0),
                    batch.get('stage3', {}).get('skipped', 0),
                    batch.get('stage3', {}).get('errors', [])
                )
            return

        
    except Exception as e:
        error_msg = f"Error in process_stage3: {str(e)}"
        logger.error(error_msg)
        update_batch_status(batch_id, "stage3", error_msg=error_msg)

def send_processing_summary_email(processing_stage, total_articles, total_skipped, error_articles):
    subject = f"Env::{stage}, Essence Feed Processing Summary, Stage::{processing_stage}"
    body = f"""
        Feed processing completed.
        """
    if processing_stage == "stage1":
        body += "Stage 1 :: Extracted transcripts, summaries, categories, and other metadata from enabled feeds."
    elif processing_stage == "stage2":
        body += "Stage 2 :: Deduplication and creating audio summaries for processed articles."
    elif processing_stage == "stage3":
        body += "Stage 3 :: Creating user feeds based on processed articles."
    body += f"""

        Total articles processed: {total_articles}
        Total articles skipped: {total_skipped}
        Total articles with errors: {len(error_articles)}

        Articles with errors:
        """
    
    for article in error_articles:
        body += f"- URL: {article['url']}\n  Error: {article['error']}\n"

    send_email(ADMIN_EMAIL, subject, body)


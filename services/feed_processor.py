import requests
from io import BytesIO
import datetime  # Add this import at the top
import hashlib  # Add this import at the top
import config
import random

from services import utilities
from lib.log import logger
from services import podcaster
from models.audio_story_request import AudioStoryRequest
from util import llm_util, email_util, vector_util, date_util
import config
from util import string_util
from services import user_feed
from util import feed_util
from db.factory import db_factory

stage = config.STAGE

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
            'batch_id': batch_id,
            'total_feeds': len(feeds),
            'start_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        feed_batch_repo.create_batch(batch_record)

        # Start a background task for each feed
        for feed in feeds:
            try:
                # Include batch_id in the background task parameters
                utilities.background_task('services.feed_processor.process_stage1', feed, batch_id)
                logger.info(f"Started background task for feed {feed['id']} in batch {batch_id}")
            except Exception as e:
                error_msg = f"Error starting background task for feed {feed['id']}: {str(e)}"
                logger.error(error_msg)

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

        if rss_type == 'rss.app':
            processed_count, skipped_count, errors = process_stage1_rssapp(source_name, category, feed_url)

        # Update the last processed date
        feed['last_processed_date'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        feed_repo.update(feed)

        feed_batch_repo.increment_completed_feeds(batch_id)
        feed_batch_repo.update_stage_status(batch_id, stage="stage1", processed=processed_count, skipped=skipped_count, errors=errors)

        # Check if all feeds are processed
        batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
        if batch and batch['completed_feeds'] >= batch['total_feeds']:
            logger.info(f"Completed processing stage1 for batch {batch_id}")
            # Mark stage1 as complete
            feed_batch_repo.mark_stage_complete(
                batch_id=batch_id,
                stage='stage1',
                end_time=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            
            # Trigger stage2
            utilities.background_task('services.feed_processor.process_stage2', batch_id)
        return

    except Exception as e:
        error_msg = f"Error processing feed {feed.get('id', 'unknown')}: {str(e)}"
        logger.error(error_msg)
        return
    
# Parses the feed from rss.app
def process_stage1_rssapp(source_name, category, feed_url):
    logger.info(f"process_stage1_rssapp for feed_url: {feed_url}")
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
                errors.append(f"{item.get('url', 'Unknown URL')}: {error_msg}")
    else:
        error_msg = f"Failed to fetch feed from {feed_url}"
        logger.error(error_msg)
        errors.append(f"{feed_url}: {error_msg}")
    
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
    
    if not config.SKIP_SUMMARY_CREATION:
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
            logger.info(f"Article {article_id} already exists. Current status: {existing_article.get('processing_status')}")
            return existing_article
        
        # Handle date_published
        date_published = date_util.format_date_published(item.get('date_published'))
        
        # Create new article
        new_article = {
            'id': article_id,
            'public_key': string_util.generate_short_key(article_id),
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
            summary_vector = vector_util.get_article_embedding_normalized(article)
            article['summary_vector'] = summary_vector
        else:
            article['processing_status'] = 'discarded_after_summaries_extracted'
        
        article_repo.addOrUpdate(article)
        logger.info(f"Summarized and extracted categories for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in summarize_and_save: {str(e)}")
        raise

def process_stage2(batch_id=None, force=False):
    """
    Stage2:
    Deduplication and creating audio summaries.
    Batching by number of articles based on lambda timeout value. Trigger a background task for each batch
    """
    try:
        logger.info(f"Processing batch {batch_id} for stage2")
        batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
        
        # NOTE: Be careful about using force=True, as it will reprocess lot of articles
        if force:
            processing_status = "audio_summary_generated"
        else:
            processing_status = "summaries_extracted"

        if batch:
            articles_to_process = article_repo.query_by_status(processing_status, start_date=batch['start_time'], limit=1000)
        else:   
            articles_to_process = article_repo.query_by_status(processing_status, limit=1000)
        
        logger.info(f"Found {len(articles_to_process)} articles with '{processing_status}'")
        
        # Perform deduplication
        duplicate_articles, deduplicated_articles = vector_util.deduplicate_articles(articles_to_process)
        article_repo.bulk_update_partial(duplicate_articles)

        # Rank articles by importance
        # article_scores = llm_util.rank_articles_by_importance_batched(deduplicated_articles)
        # if article_scores:
        #     article_repo.bulk_update_partial(article_scores)

        # Start processing first batch
        utilities.background_task('services.feed_processor.generate_audio_summaries_batch', 
                                batch_id, 
                                start_date=batch['start_time'] if batch else None)
        
        logger.info(f"Initiated audio summary generation for stage2 processing for batch {batch_id}")
                
    except Exception as e:
        error_msg = f"Error processing stage2 for batch {batch_id}: {str(e)}"
        logger.error(error_msg)

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
            
            # Trigger stage3
            utilities.background_task('services.feed_processor.process_stage3', batch_id)
            return
        
        logger.info(f"generate_audio_summaries_batch >> Processing batch of {len(articles_to_process)} articles")
        
        processed_count = 0
        error_count = 0
        error_articles = []
        
        for article in articles_to_process:
            try:
                # Verify article is still in correct state before processing
                current_article = article_repo.get(article['id'])
                if current_article and current_article['processing_status'] != 'summaries_extracted':
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
                error_articles.append(f"{article.get('url', 'Unknown')}: {error_msg}")
                
                # Reset article status and record error
                article['processing_status'] = 'summaries_extracted'
                article_repo.addOrUpdate(article)
                
        skipped = len(articles_to_process) - processed_count
        feed_batch_repo.update_stage_status(batch_id, "stage2", processed=processed_count, skipped=skipped, errors=error_articles)
        logger.info(f"generate_audio_summaries_batch >> Batch : {batch_id} Processed {processed_count} articles, skipped {skipped} articles, with {error_count} errors")
        # Trigger next batch
        utilities.background_task('services.feed_processor.generate_audio_summaries_batch', 
                                batch_id, 
                                start_date=start_date)
        
    except Exception as e:
        error_msg = f"Error in generate_audio_summaries_batch: {str(e)}"
        logger.error(error_msg)
        

def generate_and_save_audio_summary(article, previous_article=None):
    try:
        logger.info(f"Generating audio summary for article {article['id']}")
        # Randomly set two_speakers to True or False
        two_speakers = random.random() < 0.3

        # TODO - No user specific customizations are happening now. 
        audio_request = AudioStoryRequest(
            id=article['id'],
            text_summary=article.get('summary_200'),
            url=article.get('url'),
            length="short",
            language="en",
            region="UK",
            two_speakers=two_speakers,
            add_background=True,
            user_name=None,
            previous_article=previous_article.get('summary_50') if previous_article else None
        )
        audio_summary, conversation = podcaster.generate_audio_story(audio_request)
        
        if audio_summary:
            # Build the streaming response object and upload to S3
            output = BytesIO()
            audio_summary.export(output, format="mp3")

            s3_url = utilities.upload_audiostory_to_s3(audio_request, output)
            article['audio_summary'] = s3_url
            
            article['processing_status'] = 'audio_summary_generated'
            article_repo.addOrUpdate(article)
            logger.info(f"Generated and saved audio summary for article {article['id']}")
            return
        
        if config.SKIP_AUDIO_GENERATION:
            article['processing_status'] = 'audio_summary_generated'
            article_repo.addOrUpdate(article)
            logger.info(f"Skipping audio generation for article {article['id']}")
    except Exception as e:
        logger.error(f"Error in generate_and_save_audio_summary: {str(e)}")
        # Reset article status and record error
        article['processing_status'] = 'summaries_extracted'
        article_repo.addOrUpdate(article)

def process_stage3(batch_id=None, user_offset=0, batch_size=10):
    """
    Stage3: Creating user feeds.
    Process a batch of users for feed creation.
    Will trigger next batch if more users exist.
    """
    try:
        # Get next batch of users
        active_users = user_feed.get_active_users(offset=user_offset, limit=batch_size)
                
        logger.info(f"process_stage3 >> Batch : {batch_id} Processing batch of {len(active_users)} users (offset: {user_offset})")
        
        if active_users and len(active_users) > 0:
            # Process the batch of users
            error_users = user_feed.create_feeds_for_users(active_users, batch_id)
            processed_count = len(active_users) - len(error_users) if error_users else len(active_users)
            skipped_count = len(error_users) if error_users else 0
            feed_batch_repo.update_stage_status(batch_id, "stage3", processed=processed_count, skipped=skipped_count, errors=error_users)
            
            # Trigger next batch
            next_offset = user_offset + batch_size
            utilities.background_task('services.feed_processor.process_stage3', 
                                    batch_id, 
                                    user_offset=next_offset)
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
                email_util.send_processing_summary_email(batch)
            return

    except Exception as e:
        error_msg = f"Error in process_stage3: {str(e)}"
        logger.error(error_msg)



from flask import Blueprint, request, jsonify, send_file
from lib.log import logger
from db import db
import uuid
from util import llm_util
from util import vector_util
from opensearchpy import OpenSearch
from config import OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_INDEX
import numpy as np
import json
from datetime import datetime, timedelta
import csv
import threading
import time
import os
from services import podcaster
from io import BytesIO
from models.user import User
from db.repo.user_repository import UserRepository
from uuid import uuid4
from lib.validators import validate_email
from werkzeug.exceptions import BadRequest
from services import utilities
from services.user_management import update_user_preferences
from services import user_news

internal_bp = Blueprint('internal', __name__)

user_repository = UserRepository()

@internal_bp.route('/personalized_feed', methods=['GET'])
def personalized_feed():
    request_id = str(uuid.uuid4())
    logger.info(f"personalized_feed route - Request ID: {request_id}")
    try:
        # Get the logged-in user's ID (you'll need to implement user authentication)
        email = request.args.get('email')  
        count = request.args.get('count', default=20, type=int)      
        user = user_repository.get_by_email(email)
        # Get the user's preferences
        user_preferences_vector = user.preferences.get('structured_vector', None)
        if user_preferences_vector is None:
            user_preferences_vector = user.preferences.get('flat_vector', None)
        
        if user_preferences_vector is None:
            return jsonify({"error": "User preferences not found"}), 404
        
        articles = db.query_articles_for_user(user_preferences_vector, limit=count)
        
        return jsonify(articles), 200
    except Exception as e:
        logger.error(f"Error in personalized_feed route: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Helper functions (implement these based on your application's structure)
def get_logged_in_user_id():
    # Implement user authentication and return the user ID
    return "jackson"

def get_user_preferences(user_id, type="flat"):
    jackson = """
    {
        "Geography": {
            "values": [
                "Germany",
                "Rest of mainland Europe",
                "UK",
                "US",
                "India",
                "Rest of World"
            ],
            "exclude_values": [],
            "priority_order": true
        },
        "Distribution channel": {
            "values": [
                "Online",
                "Offline"
            ],
            "exclude_values": [],
            "priority_order": true
        },
        "Industry": {
            "values": [
                "Fashion",
                "Sports",
                "Tech",
                "Electronics",
                "Retail"
            ],
            "exclude_values": [
                "Grocery"
            ],
            "priority_order": true
        },
        "Function": {
            "values": [
                "Merchandising",
                "Planning",
                "Cataloguing",
                "Retail Trading",
                "Site Merchandising",
                "User Experience",
                "Product",
                "Tech Platform",
                "OMS / WMS / ERP",
                "Pricing",
                "Online marketing",
                "Social / SEA /SEO / Affiliates",
                "CRM",
                "Warehousing",
                "last mile",
                "Analytics / BI",
                "Customer support"
            ],
            "exclude_values": [],
            "priority_order": false
        },
        "Topics": {
            "values": [
                "Financial numbers",
                "Executive movements",
                "New product launches",
                "Stock market movements",
                "Mergers and acquisitions",
                "Regulations"
            ],
            "exclude_values": ["Black Friday"],
            "priority_order": false
        },
        "Companies": {
            "values": [
                "LVMH",
                "Hugo Boss",
                "PVH",
                "Kering",
                "Ralph Lauren",
                "Zara",
                "H&M",
                "Uniqlo",
                "Nike",
                "Adidas",
                "ON",
                "Hoka",
                "UnderArmour",
                "Lululemon",
                "amazon",   
                "Zalando",
                "JD",
                "Aboutyou", 
                "Asos",
                "shein",
                "Otto",
                "ebay",
                "Unisport"                  
            ],
            "exclude_values": ["Temu"],
            "priority_order": false
        }
    }
    """

    bala_ = """
    {
        "Geography": {
            "values": [
                "UK",
                "US",
                "India",
                "China",
                "Rest of World"
            ],
            "exclude_values": [],
            "priority_order": false
        },
        "Topics": {
            "values": ["All"],
            "exclude_values": [],
            "priority_order": false
        },
        "Companies": {
            "values": ["All"],
            "exclude_values": [],
            "priority_order": false
        }
    }
    """

    bala = """Everything related to fashion and grocery"""

    tony = """
    {
        "Geography": {
            "values": [
                "UK",
                "US",
                "India",
                "China",
                "Rest of World"
            ],
            "exclude_values": [],
            "priority_order": false
        },
        "Distribution channel": {
            "values": [
                "Online",
                "Offline"
            ],
            "exclude_values": [],
            "priority_order": false
        },
        "Industry": {
            "values": [
                "Grocery",
                "Food",
                "Retail",
                "CPG"
            ],
            "exclude_values": [
                "Tech",
                "Electronics",
                "Fashion"            
            ],
            "priority_order": false
        },
        "Topics": {
            "values": [
                "Growth",
                "Ecommerce",
                "Financial numbers",
                "Trends",
                "Quick commerce",
                "Executive movements",
                "New product launches",
                "Stock market movements",
                "Mergers and acquisitions"
            ],
            "exclude_values": [],
            "priority_order": false
        },
        "Companies": {
            "values": [
                "Nestle",
                "Pepsi",
                "Unilever",
                "M&S",
                "Lidl",
                "Aldi",
                "Costco",
                "Walmart",
                "Target",
                "Best Buy",
                "Home Depot",
                "Lowe's",
                "Amazon"
            ],
            "exclude_values": [],
            "priority_order": false
        }
    }
    """

    jackson_dict = json.loads(jackson)  
    tony_dict = json.loads(tony)  
    bala_dict = json.loads(bala_)  

    if type == "flat":
        if user_id == "jackson":
            return vector_util.create_flat_embedding(jackson)
        elif user_id == "tony":
            return vector_util.create_flat_embedding(tony)
        elif user_id == "bala":
            return vector_util.create_flat_embedding(bala)
        else:
            return None
    else:
        if user_id == "jackson":
            return vector_util.create_user_embedding(jackson_dict)
        elif user_id == "tony":
            return vector_util.create_user_embedding(tony_dict)
        elif user_id == "bala":
            return vector_util.create_user_embedding(bala_dict)
        else:
            return None

@internal_bp.route('/categorize_articles', methods=['GET'])
def categorize_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"categorize_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=500, type=int)
        processing_status = request.args.get('processing_status', default='audio_summary_generated')

        # Start the categorization process in a separate thread
        thread = threading.Thread(target=categorize_articles_background, args=(limit, processing_status, request_id))
        thread.start()

        return jsonify({"message": "Categorization process started", "request_id": request_id}), 202
    except Exception as e:
        logger.error(f"Error in categorize_articles route: {str(e)}")
        return jsonify({"error": str(e)}), 500

def categorize_articles_background(limit, processing_status, request_id):
    logger.info(f"Starting background categorization - Request ID: {request_id}")
    try:
        table = db.get_article_table()
        total_processed = 0
        last_evaluated_key = None
        batch_size = 100

        while True:
            articles, last_evaluated_key = table.query_articles(
                processing_status=processing_status,
                last_evaluated_key=last_evaluated_key,
                batch_size=batch_size
            )

            if articles is None:
                logger.warning("Throughput exceeded, waiting before retry...")
                time.sleep(1)  # Wait for 1 second before retrying
                continue

            logger.info(f"Processing batch of {len(articles)} articles")
            for article in articles:
                categorize_article(article)
                total_processed += 1

                if limit and total_processed >= limit:
                    logger.info(f"Reached limit of {limit} articles")
                    return

            if not last_evaluated_key:
                break

            time.sleep(0.5)  # Add a small delay between batches to reduce the risk of throttling

        logger.info(f"Categorization completed - Processed {total_processed} articles - Request ID: {request_id}")
    except Exception as e:
        logger.error(f"Error in background categorization - Request ID: {request_id}: {str(e)}")

def categorize_article(article):
    try:
        # Generate vector embedding for the article's summary_200
        summary = article.get('summary_200', '')
        embedding = llm_util.get_embedding(summary)
        
        # Convert the embedding to a numpy array and normalize it
        embedding_array = np.array(embedding)
        if np.all(embedding_array == 0):
            logger.warning(f"Zero embedding generated for article {article['id']}")
            normalized_embedding = embedding_array
        else:
            normalized_embedding = embedding_array / np.linalg.norm(embedding_array)
        
        # Convert the normalized embedding back to a list of floats
        normalized_embedding_list = normalized_embedding.tolist()
        
        # Prepare the document to be indexed in OpenSearch
        doc = {
            'article_id': article['id'],
            'summary_vector': normalized_embedding_list,
            'summary_200': summary,
            'summary_50': article.get('summary_50', ''),
            'title': article.get('title', ''),
            'url': article.get('url', ''),
            'image': article.get('image', ''),
            'date_published': article.get('date_published', ''),
            'rss_summary': article.get('rss_summary', ''),
            'source_name': article.get('source_name', ''),
            'type': article.get('type', ''),
            'categories': article.get('categories', []),
            'audio_summary': article.get('audio_summary', ''),
            'processing_status': article.get('processing_status', '')
        }
        
        # Get the OpenSearch client
        client = db.get_opensearch_client()
        
        # Index the document in OpenSearch
        response = client.index(
            index=OPENSEARCH_INDEX,
            body=doc,
            id=article['id'],
            refresh=True
        )
        
        logger.info(f"Article {article['id']} indexed in OpenSearch: {response['result']}")        
    except Exception as e:
        logger.error(f"Error in categorize_article: {str(e)}")
        return article

@internal_bp.route('/generate_daily_top_articles', methods=['GET'])
def generate_daily_top_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"generate_daily_top_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        user_id = request.args.get('user_id')
        type = request.args.get('type', default="flat")
        user_preferences_vector = get_user_preferences(user_id, type)

        start_date = request.args.get('start_date', default=(datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', default=datetime.now().strftime('%Y-%m-%d'))

        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')

        client = db.get_opensearch_client()

        # Define the output file path
        output_dir = 'output'
        os.makedirs(output_dir, exist_ok=True)
        file_name = f'daily_top_articles_{user_id or "all"}_{start_date.strftime("%Y-%m-%d")}_{end_date.strftime("%Y-%m-%d")}.csv'
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['id', 'title', 'url', 'summary_50', 'type', 'categories', 'date_published', 'score'])

            current_date = start_date
            while current_date <= end_date:
                if user_id:
                    # Get user preferences and perform vector search
                    query = {
                        "size": 20,
                        "query": {
                            "script_score": {
                                "query": {
                                    "bool": {
                                        "filter": [
                                            {
                                                "range": {
                                                    "date_published": {
                                                        "gte": current_date.strftime('%Y-%m-%d'),
                                                        "lt": (current_date + timedelta(days=1)).strftime('%Y-%m-%d')
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                },
                                "script": {
                                    "source": "cosineSimilarity(params.query_vector, doc['summary_vector']) + 1.0",
                                    "params": {
                                        "query_vector": user_preferences_vector.tolist()
                                    }
                                }
                            }
                        }
                    }
                else:
                    # No user_id provided, fetch all articles for the day without vector search
                    query = {
                        "size": 1000,  # Increase size to get more articles per day
                        "query": {
                            "range": {
                                "date_published": {
                                    "gte": current_date.strftime('%Y-%m-%d'),
                                    "lt": (current_date + timedelta(days=1)).strftime('%Y-%m-%d')
                                }
                            }
                        },
                        "sort": [
                            {"date_published": "desc"}
                        ]
                    }

                response = client.search(index=db.OPENSEARCH_INDEX, body=query)
                logger.debug(f"Response hits count: {len(response['hits']['hits'])}")

                for hit in response['hits']['hits']:
                    article = hit['_source']
                    writer.writerow([
                        article.get('article_id', ''),
                        article.get('title', ''),
                        article.get('url', ''),
                        article.get('summary_50', ''),
                        article.get('type', ''),
                        ','.join(str(cat) for cat in article.get('categories', [])),
                        article.get('date_published', ''),
                        hit['_score'] if user_id else ''
                    ])

                current_date += timedelta(days=1)

        logger.info(f"CSV file generated: {file_path}")
        return jsonify({"message": f"CSV file generated successfully", "file_path": file_path}), 200

    except Exception as e:
        logger.error(f"Error in generate_daily_top_articles route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route('/text_to_audio', methods=['POST'])
def text_to_audio():
    request_id = str(uuid.uuid4())
    logger.info(f"text_to_audio route - Request ID: {request_id}")
    try:
        data = request.json
        text = data.get('text')
        speaker = data.get('speaker', 'male')  # Default to male if not specified
        language = data.get('language', 'en')  # Default to English if not specified

        if not text:
            return jsonify({"error": "Text is required"}), 400

        # Generate audio using the podcaster service
        audio_segment = podcaster.generate_audio(speaker, text, language)

        # Convert the audio segment to a byte stream
        audio_bytes = BytesIO()
        audio_segment.export(audio_bytes, format="mp3")
        audio_bytes.seek(0)

        # Send the audio file as a response
        return send_file(
            audio_bytes,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"audio_{request_id}.mp3"
        )

    except Exception as e:
        logger.error(f"Error in text_to_audio route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route('/flush_user_history', methods=['GET'])
def flush_user_history():
    request_id = str(uuid.uuid4())
    logger.info(f"flush_user_history route - Request ID: {request_id}")
    try:
        email = request.args.get('email')

        if not email:
            return jsonify({"error": "Email is required"}), 400

        # Get the user by email
        user = user_repository.get_by_email(email)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get the user_listen_history table
        user_history_table = db.get_user_listen_history_table()

        # Delete the user's history
        result = user_history_table.delete(user.id)

        if result:
            logger.info(f"User history flushed for user ID: {user.id}")
            return jsonify({"message": "User listening history flushed successfully"}), 200
        else:
            logger.warning(f"No history found to flush for user ID: {user.id}")
            return jsonify({"message": "No listening history found for the user"}), 200

    except Exception as e:
        logger.error(f"Error in flush_user_history route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route('/add_feeds', methods=['POST'])
def add_feeds():
    request_id = str(uuid.uuid4())
    logger.info(f"add_feeds route - Request ID: {request_id}")
    try:
        data = request.json
        if not isinstance(data, list):
            data = [data]  # Convert single object to list

        table = db.get_feed_table()
        added_feeds = []

        for feed in data:
            # Validate mandatory fields
            mandatory_fields = ['category', 'feed_url', 'rss_type', 'source_name']
            if not all(field in feed for field in mandatory_fields):
                return jsonify({"error": f"Missing mandatory field(s) in feed: {feed}"}), 400

            # Prepare item for DynamoDB
            new_feed = {
                'id': str(uuid4()),  # Auto-generate ID
                'category': feed['category'],
                'feed_url': feed['feed_url'],
                'rss_type': feed['rss_type'],
                'source_name': feed['source_name'],
                'status': 'disabled',  # Set status to disabled by default
                'last_processed_date': datetime.now().isoformat()  # Set current time as last processed date
            }

            # Add to DynamoDB
            table.addOrUpdate(new_feed)
            added_feeds.append(new_feed)

        return jsonify({"message": f"Successfully added {len(added_feeds)} feeds", "feeds": added_feeds}), 201

    except Exception as e:
        logger.error(f"Error in add_feeds route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route('/create_user_from_form', methods=['POST'])
def create_user_from_form():
    logger.info("create_user_from_form route")
    try:
        data = request.json
        email = data.get('email')
        if not email or not validate_email(email):
            raise BadRequest("Invalid or missing email")

        # Check if user already exists
        existing_user = user_repository.get_by_email(email)
        if existing_user:
            return jsonify({"message": "User already exists", "user_id": existing_user.id}), 200

        # Create new user
        new_user = User(email=email, first_name=email.split('@')[0], country='Unknown', language='en')
        user_repository.create(new_user)

        # Process preferences
        preferences = process_form_preferences(data)
        
        # Update user preferences
        utilities.background_task(update_user_preferences, new_user.id, json.dumps(preferences))

        return jsonify({
            "message": "User created and preferences update initiated",
            "user_id": new_user.id
        }), 201

    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in create_user_from_form: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

def process_form_preferences(data):
    preferences = {
        "Industry": {"values": data.get("industries", "").split(", ")},
        "Geography": {"values": data.get("geographies", "").split(", ")},
        "Topics": {"values": data.get("news_topics", "").split(", ")},
        "Companies": {"values": data.get("brands_retailers", "").split(", ")},
    }
    
    # Add any additional information from the "What have we missed?" field
    additional_info = data.get("additional_info")
    if additional_info:
        preferences["Additional Information"] = {"values": [additional_info]}

    return preferences

@internal_bp.route('/latest_news', methods=['GET'])
def internal_latest_news():
    request_id = str(uuid.uuid4())
    logger.info(f"internal_latest_news route - Request ID: {request_id}")
    try:
        # Get email from query parameters
        email = request.args.get('email')
        if not email:
            return jsonify({"error": "Email parameter is required"}), 400

        # Get optional parameters
        categories = request.args.getlist('categories')
        limit = int(request.args.get('limit', 10))

        # Get user from repository
        user = user_repository.get_by_email(email)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # If categories is empty, fetch from user table
        if not categories:
            categories = user.categories if hasattr(user, 'categories') else None


        # Get articles using the user_news service
        articles = user_news.get_latest_news(user, categories, limit)

        return jsonify({
            "articles": articles,
            "count": len(articles)
        }), 200

    except Exception as e:
        logger.error(f"Error in internal_latest_news route: {str(e)}")
        return jsonify({"error": str(e)}), 500

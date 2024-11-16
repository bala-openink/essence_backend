from flask import Blueprint, request, jsonify, send_file
from lib.log import logger
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
import copy
import os
from services import podcaster
from io import BytesIO
from models.user import User
from uuid import uuid4
from lib.validators import validate_email
from werkzeug.exceptions import BadRequest
from services import utilities
from services.user_management import update_user_preferences
from services import user_news
from models.audio_story_request import AudioStoryRequest
from db.factory import db_factory

internal_bp = Blueprint("internal", __name__)

user_repository = db_factory.get_user_repository()
user_listen_history_repo = db_factory.get_generic_repository("user_listen_history")
article_repo = db_factory.get_article_repository()
feed_repo = db_factory.get_generic_repository("feed")

@internal_bp.route("/generate_custom_podcast", methods=["POST"])
def generate_custom_podcast():
    request_id = str(uuid.uuid4())
    logger.info(f"generate_custom_podcast route - Request ID: {request_id}")
    try:
        data = request.json
        if data is None:
            raise BadRequest("No data received")
        
        logger.info(f"Received request data - Request ID: {request_id}")
        logger.debug(f"Request payload: {json.dumps(data, indent=2)}")

        # Validate required inputs
        if not all(key in data for key in ["search_query", "duration_minutes"]):
            logger.error(f"Missing required fields - Request ID: {request_id}")
            return (
                jsonify(
                    {
                        "error": "Missing required fields: search_query and duration_minutes"
                    }
                ),
                400,
            )

        search_query = data["search_query"]
        narrative_prompt = data.get("narrative_prompt", search_query)
        duration_minutes = int(data["duration_minutes"])
        start_date = data.get(
            "start_date", 
            (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        )
        end_date = data.get(
            "end_date", 
            datetime.now().strftime("%Y-%m-%d")
        )

        # Convert to ISO format using parse_iso_date
        if start_date:
            start_date = user_news.parse_iso_date(start_date).isoformat()
        if end_date:
            end_date = user_news.parse_iso_date(end_date).isoformat()

        language = data.get("language", "en")
        region = data.get("region", "US")

        logger.info(
            f"Generating embedding for search query: '{search_query}' - Request ID: {request_id}"
        )
        query_vector = llm_util.get_embedding_normalized(search_query)

        # Debug vector properties
        logger.debug(f"Query vector type: {type(query_vector)}")
        logger.debug(f"Query vector shape: {query_vector.shape}")
        logger.debug(f"Query vector sample (first 5 elements): {query_vector[:5]}")

        query = {
            "size": 20,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"processing_status": "audio_summary_generated"}}
                    ]
                }
            },
            "sort": [{"date_published": "desc"}]
        }

        if start_date or end_date:
            date_range = {"range": {"date_published": {}}}
            if start_date:
                date_range["range"]["date_published"]["gte"] = start_date
            if end_date:
                date_range["range"]["date_published"]["lte"] = end_date
            query["query"]["bool"]["filter"].append(date_range)

        query["query"] = {
            "script_score": {
                "query": query["query"],
                "script": {
                    "source": "cosineSimilarity(params.query_vector, doc['summary_vector']) + 1.0",
                    "params": {"query_vector": query_vector.tolist()}
                }
            }
        }
        query["sort"] = [{"_score": "desc"}, {"date_published": "desc"}]

        logger.info(
            f"Querying OpenSearch for articles between {start_date} and {end_date} - Request ID: {request_id}"
        )

        # Log the full query for debugging
        debug_query = copy.deepcopy(query)
        debug_query['query']['script_score']['script']['params']['query_vector'] = '[vector truncated]'
        logger.debug(f"OpenSearch query: {json.dumps(debug_query, indent=2)}")

        articles = []
        try:
            response = article_repo.search(query)
            logger.debug(f"OpenSearch response: {json.dumps(response, indent=2)}")
            articles = [hit["_source"] for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.error(f"OpenSearch error details - Request ID: {request_id}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error message: {str(e)}")
            if hasattr(e, 'info'):
                logger.error(f"Error info: {json.dumps(e.info, indent=2)}")
            raise        

        logger.info(
            f"Found {len(articles)} relevant articles - Request ID: {request_id}"
        )
        if not articles:
            logger.warning(
                f"No articles found for query: '{search_query}' - Request ID: {request_id}"
            )
            return jsonify({"error": "No relevant articles found"}), 404

        # Log titles of found articles
        logger.debug(f"Retrieved articles - Request ID: {request_id}:")
        for idx, article in enumerate(articles, 1):
            logger.debug(
                f"{idx}. {article.get('title', 'No title')} ({article.get('date_published', 'No date')})"
            )

        # Prepare articles summary
        logger.info(
            f"Preparing comprehensive summary of {len(articles)} articles - Request ID: {request_id}"
        )
        articles_summary = "\n\n".join(
            [
                f"Article from {article.get('date_published', 'unknown date')}:\n"
                f"Title: {article.get('title', '')}\n"
                f"{article.get('summary_200', '')}"
                for article in articles
            ]
        )

        # Create narrative prompt
        logger.info(f"Creating podcast narrative prompt - Request ID: {request_id}")
        podcast_prompt = f"""
        Create a natural, engaging podcast conversation about the topic, {narrative_prompt} using all the relevant articles provided in a cohesive and a natural sounding manner. 

        Key requirements:
        2. Target duration: {duration_minutes} minutes (approximately {duration_minutes * 150} words)
        3. Make it sound as human like as possible and it should feel like a natural conversation between two hosts, who are very familiar with the topic and with each other.
        4. Include relevant dates, amounts, other details and context where appropriate
        5. The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region.
        6. Return the output as valid clean JSON without any additional prefixes or formatting, in this format  {{'male': 'male dialogue', 'female': 'female dialogue',...}}"
        """

        # Generate the podcast conversation
        logger.info(f"Generating podcast conversation - Request ID: {request_id}")
        audioStoryRequest = AudioStoryRequest(
            id=request_id,
            text_summary=articles_summary,
            length="long",
            language=language,
            region=region,
            two_speakers=True,
            user_name=None,
            previous_article=None,
            new_instructions=podcast_prompt,
        )

        logger.info(f"Generating audio for podcast - Request ID: {request_id}")
        start_time = time.time()
        podcast_audio = podcaster.generate_audio_story(audioStoryRequest)
        generation_time = time.time() - start_time
        logger.info(
            f"Audio generation completed in {generation_time:.2f} seconds - Request ID: {request_id}"
        )

        # Convert to bytes and prepare response
        logger.info(f"Preparing audio response - Request ID: {request_id}")
        audio_bytes = BytesIO()
        podcast_audio.export(audio_bytes, format="mp3")
        audio_bytes.seek(0)

        logger.info(f"Successfully generated custom podcast - Request ID: {request_id}")
        return send_file(
            audio_bytes,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"custom_podcast_{request_id}.mp3",
        )

    except Exception as e:
        logger.error(
            f"Error in generate_custom_podcast route - Request ID: {request_id}: {str(e)}",
            exc_info=True,
        )
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/personalized_feed", methods=["GET"])
def personalized_feed():
    request_id = str(uuid.uuid4())
    logger.info(f"personalized_feed route - Request ID: {request_id}")
    try:
        # Get the logged-in user's ID (you'll need to implement user authentication)
        email = request.args.get("email")
        count = request.args.get("count", default=20, type=int)
        if email is None:
            raise BadRequest("No email received")
        
        user = user_repository.get_by_email(email)
        if user is None:
            raise BadRequest("User not found")
        
        # Get the user's preferences
        user_preferences_vector = user.preferences.get("structured_vector", None)
        if user_preferences_vector is None:
            user_preferences_vector = user.preferences.get("flat_vector", None)

        if user_preferences_vector is None:
            return jsonify({"error": "User preferences not found"}), 404

        articles = article_repo.query_by_vector(user_preferences_vector, limit=count)
        articles = [user_news.prepare_for_transport(article) for article in articles]

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


@internal_bp.route("/categorize_articles", methods=["GET"])
def categorize_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"categorize_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get("limit", default=500, type=int)
        processing_status = request.args.get(
            "processing_status", default="audio_summary_generated"
        )

        # Start the categorization process in a separate thread
        thread = threading.Thread(
            target=categorize_articles_background,
            args=(limit, processing_status, request_id),
        )
        thread.start()

        return (
            jsonify(
                {"message": "Categorization process started", "request_id": request_id}
            ),
            202,
        )
    except Exception as e:
        logger.error(f"Error in categorize_articles route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route("/generate_daily_top_articles", methods=["GET"])
def generate_daily_top_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"generate_daily_top_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        user_id = request.args.get("user_id")
        type = request.args.get("type", default="flat")
        user_preferences_vector = get_user_preferences(user_id, type)

        start_date = request.args.get(
            "start_date",
            default=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
        )
        end_date = request.args.get(
            "end_date", default=datetime.now().strftime("%Y-%m-%d")
        )

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

        # Define the output file path
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        file_name = f'daily_top_articles_{user_id or "all"}_{start_date.strftime("%Y-%m-%d")}_{end_date.strftime("%Y-%m-%d")}.csv'
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "id",
                    "title",
                    "url",
                    "summary_50",
                    "type",
                    "categories",
                    "date_published",
                    "score",
                ]
            )

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
                                                        "gte": current_date.strftime(
                                                            "%Y-%m-%d"
                                                        ),
                                                        "lt": (
                                                            current_date
                                                            + timedelta(days=1)
                                                        ).strftime("%Y-%m-%d"),
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
                                    },
                                },
                            }
                        },
                    }
                else:
                    # No user_id provided, fetch all articles for the day without vector search
                    query = {
                        "size": 1000,  # Increase size to get more articles per day
                        "query": {
                            "range": {
                                "date_published": {
                                    "gte": current_date.strftime("%Y-%m-%d"),
                                    "lt": (current_date + timedelta(days=1)).strftime(
                                        "%Y-%m-%d"
                                    ),
                                }
                            }
                        },
                        "sort": [{"date_published": "desc"}],
                    }

                response = article_repo.search(query)
                logger.debug(f"Response hits count: {len(response['hits']['hits'])}")

                for hit in response["hits"]["hits"]:
                    article = hit["_source"]
                    writer.writerow(
                        [
                            article.get("article_id", ""),
                            article.get("title", ""),
                            article.get("url", ""),
                            article.get("summary_50", ""),
                            article.get("type", ""),
                            ",".join(str(cat) for cat in article.get("categories", [])),
                            article.get("date_published", ""),
                            hit["_score"] if user_id else "",
                        ]
                    )

                current_date += timedelta(days=1)

        logger.info(f"CSV file generated: {file_path}")
        return (
            jsonify(
                {"message": f"CSV file generated successfully", "file_path": file_path}
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Error in generate_daily_top_articles route: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/text_to_audio", methods=["POST"])
def text_to_audio():
    request_id = str(uuid.uuid4())
    logger.info(f"text_to_audio route - Request ID: {request_id}")
    try:
        data = request.json
        text = data.get("text")
        speaker = data.get("speaker", "male")  # Default to male if not specified
        language = data.get("language", "en")  # Default to English if not specified

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
            download_name=f"audio_{request_id}.mp3",
        )

    except Exception as e:
        logger.error(f"Error in text_to_audio route: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/flush_user_history", methods=["GET"])
def flush_user_history():
    request_id = str(uuid.uuid4())
    logger.info(f"flush_user_history route - Request ID: {request_id}")
    try:
        email = request.args.get("email")

        if not email:
            return jsonify({"error": "Email is required"}), 400

        # Get the user by email
        user = user_repository.get_by_email(email)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Delete the user's history
        result = user_listen_history_repo.delete(user.id)

        if result:
            logger.info(f"User history flushed for user ID: {user.id}")
            return (
                jsonify({"message": "User listening history flushed successfully"}),
                200,
            )
        else:
            logger.warning(f"No history found to flush for user ID: {user.id}")
            return jsonify({"message": "No listening history found for the user"}), 200

    except Exception as e:
        logger.error(f"Error in flush_user_history route: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/add_feeds", methods=["POST"])
def add_feeds():
    request_id = str(uuid.uuid4())
    logger.info(f"add_feeds route - Request ID: {request_id}")
    try:
        data = request.json
        if not isinstance(data, list):
            data = [data]  # Convert single object to list

        added_feeds = []

        for feed in data:
            # Validate mandatory fields
            mandatory_fields = ["category", "feed_url", "rss_type", "source_name"]
            if not isinstance(feed, dict) or not all(field in feed for field in mandatory_fields):
                return (
                    jsonify({"error": f"Missing mandatory field(s) in feed: {feed}"}),
                    400,
                )

            # Prepare item for DynamoDB
            new_feed = {
                "id": str(uuid4()),  # Auto-generate ID
                "category": feed.get("category"),
                "feed_url": feed.get("feed_url"),
                "rss_type": feed.get("rss_type"),
                "source_name": feed.get("source_name"),
                "status": feed.get("status", "disabled"),  # Set status to disabled by default
                "last_processed_date": datetime.now().isoformat(),  # Set current time as last processed date
            }

            feed_repo.add(new_feed)
            added_feeds.append(new_feed)

        return (
            jsonify(
                {
                    "message": f"Successfully added {len(added_feeds)} feeds",
                    "feeds": added_feeds,
                }
            ),
            201,
        )

    except Exception as e:
        logger.error(f"Error in add_feeds route: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/create_user_from_form", methods=["POST"])
def create_user_from_form():
    logger.info("create_user_from_form route")
    try:
        data = request.json
        email = data.get("email")
        if not email or not validate_email(email):
            raise BadRequest("Invalid or missing email")

        # Check if user already exists
        existing_user = user_repository.get_by_email(email)
        if existing_user:
            return (
                jsonify(
                    {"message": "User already exists", "user_id": existing_user.id}
                ),
                200,
            )

        # Create new user
        new_user = User(
            email=email,
            first_name=email.split("@")[0],
            country="Unknown",
            language="en",
        )
        user_repository.add(new_user)

        # Process preferences
        preferences = process_form_preferences(data)

        # Update user preferences
        utilities.background_task(
            'services.user_management.update_user_preferences', new_user.id, json.dumps(preferences)
        )

        return (
            jsonify(
                {
                    "message": "User created and preferences update initiated",
                    "user_id": new_user.id,
                }
            ),
            201,
        )

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


@internal_bp.route("/latest_news", methods=["GET"])
def internal_latest_news():
    request_id = str(uuid.uuid4())
    logger.info(f"internal_latest_news route - Request ID: {request_id}")
    try:
        # Get email from query parameters
        email = request.args.get("email")
        if not email:
            return jsonify({"error": "Email parameter is required"}), 400

        # Get optional parameters
        categories = request.args.getlist("categories")
        limit = int(request.args.get("limit", 10))

        # Get user from repository
        user = user_repository.get_by_email(email)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # If categories is empty, fetch from user table
        if not categories:
            categories = user.categories if hasattr(user, "categories") else None

        # Get articles using the user_news service
        articles = user_news.get_latest_news(user, categories, limit)

        return jsonify({"articles": articles, "count": len(articles)}), 200

    except Exception as e:
        logger.error(f"Error in internal_latest_news route: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/users", methods=["GET"])
def all_users():
    request_id = str(uuid.uuid4())
    logger.info(f"test_users route - Request ID: {request_id}")
    try:
        # Get optional parameters
        status = request.args.get("status", default="verified")
        limit = request.args.get("limit", default=None, type=int)
        all_attributes = (
            request.args.get("all_attributes", default="false").lower() == "true"
        )

        users = user_repository.list_by_status(status)

        # Extract desired fields
        results = []
        for user in users:
            result = user.to_dict()

            if all_attributes:
                if "password_hash" in result:
                    del result["password_hash"]  # Remove sensitive information
            else:
                if "intro_audio_urls" in result:
                    del result["intro_audio_urls"]
                if "preferences" in result:
                    del result["preferences"]
                if "tokens" in result:
                    del result["tokens"]

            results.append(result)

        # Apply limit if specified
        if limit is not None:
            results = results[:limit]

        list_size = len(results)
        logger.info(
            f"Fetched {list_size} users from DynamoDB - Request ID: {request_id}"
        )

        # Include the list size in the response
        response = {"count": list_size, "users": results}

        return jsonify(response), 200
    except Exception as e:
        logger.error(
            f"Error fetching users: {str(e)} - Request ID: {request_id}", exc_info=True
        )
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/delete_articles", methods=["DELETE"])
def delete_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"delete_articles route - Request ID: {request_id}")
    try:
        # Get date range from query parameters
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        
        # Validate that at least one date is provided
        if not start_date and not end_date:
            return jsonify({
                "error": "At least one of start_date or end_date must be provided"
            }), 400
            
        # Convert to ISO format using parse_iso_date
        if start_date:
            start_date = user_news.parse_iso_date(start_date).isoformat()
        if end_date:
            end_date = user_news.parse_iso_date(end_date).isoformat()
            
        logger.info(f"Deleting articles between {start_date} and {end_date} - Request ID: {request_id}")
        
        # Delete articles
        deleted_count, error = article_repo.delete_by_date_range(start_date, end_date)
        
        if error:
            return jsonify({
                "error": f"Error deleting articles: {error}"
            }), 500
            
        return jsonify({
            "message": f"Successfully deleted {deleted_count} articles",
            "deleted_count": deleted_count
        }), 200
        
    except Exception as e:
        logger.error(f"Error in delete_articles route - Request ID: {request_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@internal_bp.route("/update_opensearch_mapping", methods=["POST"])
def update_opensearch_mapping():
    request_id = str(uuid.uuid4())
    logger.info(f"update_opensearch_mapping route - Request ID: {request_id}")
    try:        
        # Define the new mapping properties
        new_properties = {
            "date_created": {"type": "date"},
            "function": {"type": "text"},
            "industry": {"type": "text"},
            "region": {"type": "keyword"},
            "domain": {"type": "keyword"},
            "single_news_item": {"type": "boolean"}
        }
        
        # Update the mapping
        success, error = article_repo.update_mapping(new_properties)
        
        if success:
            return jsonify({
                "message": "OpenSearch mapping updated successfully",
                "details": new_properties
            }), 200
        else:
            return jsonify({
                "error": f"Failed to update OpenSearch mapping: {error}"
            }), 500
            
    except Exception as e:
        logger.error(f"Error updating OpenSearch mapping - Request ID: {request_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


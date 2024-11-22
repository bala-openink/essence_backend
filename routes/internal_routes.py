from flask import Blueprint, request, jsonify, send_file
from lib.log import logger
import uuid
from util import llm_util
from util import vector_util
from opensearchpy import OpenSearch
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
from util import date_util
from models.audio_story_request import AudioStoryRequest
from db.factory import db_factory
from services import user_feed
internal_bp = Blueprint("internal", __name__)

user_repository = db_factory.get_user_repository()
user_listen_history_repo = db_factory.get_generic_repository("user_listen_history")
article_repo = db_factory.get_article_repository()
feed_repo = db_factory.get_generic_repository("feed")
user_feed_repo = db_factory.get_user_feed_repository()

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
            start_date = date_util.parse_iso_date(start_date).isoformat()
        if end_date:
            end_date = date_util.parse_iso_date(end_date).isoformat()

        language = data.get("language", "en")
        region = data.get("region", "US")

        logger.info(
            f"Generating embedding for search query: '{search_query}' - Request ID: {request_id}"
        )
        query_vector = llm_util.get_embedding_for_text(search_query)

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
        Create a natural, engaging podcast conversation between the hosts, Harry and Emily using all the relevant articles provided. 

        Key requirements:
        Target duration: {duration_minutes} minutes (approximately {duration_minutes * 120} words)
        The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region.
        {narrative_prompt}
        Return the output as an array of dialogue turns in JSON format like: [{{"speaker": "male", "text": "..."}}, {{"speaker": "female", "text": "..."}}]
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
        podcast_audio, conversation = podcaster.generate_audio_story(audioStoryRequest)
        logger.info(f"Conversation: {conversation}")
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
        limit = request.args.get("limit", default=20, type=int)
        categories = request.args.getlist('categories')
        if email is None:
            raise BadRequest("No email received")
        
        user = user_repository.get_by_email(email)
        if user is None:
            raise BadRequest("User not found")
        
        articles = user_news.get_latest_news_v2(user, categories, limit)

        return jsonify(articles), 200
    except Exception as e:
        logger.error(f"Error in personalized_feed route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route("/create_user_feed", methods=["GET"])
def create_user_feed():
    request_id = str(uuid.uuid4())
    logger.info(f"create_user_feed route - Request ID: {request_id}")
    try:
        # Get the logged-in user's ID (you'll need to implement user authentication)
        email = request.args.get("email")
        if email is None:
            raise BadRequest("No email received")
        
        user = user_repository.get_by_email(email)
        if user is None:
            raise BadRequest("User not found")
        
        user_feed.create_feeds_for_user(user.id)

        return jsonify("User feed created successfully"), 200
    except Exception as e:
        logger.error(f"Error in create_user_feed route: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Helper functions (implement these based on your application's structure)
def get_logged_in_user_id():
    # Implement user authentication and return the user ID
    return "jackson"

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
    '''
    Create a new user from a form submission, update user preferences and create a user feed.
    If user exists, updates the user's preferences and creates a user feed.
    '''
    logger.info("create_user_from_form route")
    try:
        data = request.json
        if not isinstance(data, dict):
            raise BadRequest("Invalid request data")
        
        email = data.get("email")
        first_name = data.get("first_name")
        if not email or not validate_email(email):
            raise BadRequest("Invalid or missing email")

        # Check if user already exists
        user = user_repository.get_by_email(email)
        if not user:
            # Create new user
            user = User(
                email=email,
                first_name=first_name if first_name else email.split("@")[0],
                country="Unknown",
                language="en",
            )
            user_repository.add(user)
            message = "User created, preferences update and feed creation initiated"
        else:
            message = "User updated, preferences update and feed creation initiated"

        # Process preferences
        preferences = process_form_preferences(data)

        # Update user preferences
        utilities.background_task('services.user_management.update_user_preferences', user.id, json.dumps(preferences))

        return (
            jsonify(
                {
                    "message": message,
                    "user_id": user.id,
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
        **{
            k: {"values": v.split(", ")} 
            for k, v in {
                "Industry": data.get("industries"),
                "Geography": data.get("geographies"), 
                "Topics": data.get("news_topics"),
                "Companies": data.get("brands_retailers")
            }.items()
            if v and v.strip()
        }
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
        email = request.args.get("email", default=None)
        all_attributes = (
            request.args.get("all_attributes", default="false").lower() == "true"
        )

        if email:
            users = [user_repository.get_by_email(email)]
        else:
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
            start_date = date_util.parse_iso_date(start_date).isoformat()
        if end_date:
            end_date = date_util.parse_iso_date(end_date).isoformat()
            
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

@internal_bp.route('/users', methods=['GET'])
def list_users():
    request_id = str(uuid.uuid4())
    logger.info(f"list_users route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=None, type=int)
        email = request.args.get('email', default=None)
        all_attributes = request.args.get('all_attributes', default='false').lower() == 'true'

        if email:
            user = user_repository.get_by_email(email)
        else:
            users = user_repository.get_verified_users()

        # Extract desired fields
        results = []
        users_to_process = [user] if email else users

        for user in users_to_process:
            # Convert User object to dict, excluding sensitive fields
            result = user.to_dict().copy()
            
            # Always remove password hash for security
            result.pop('password_hash', None)
            
            if not all_attributes:
                # Remove additional fields when not requesting all attributes
                result.pop('intro_audio_urls', None)
                result.pop('preferences', None)

            results.append(result)

        # Apply limit if specified
        if limit is not None:
            results = results[:limit]

        list_size = len(results)
        logger.info(f"Fetched {list_size} users from DynamoDB - Request ID: {request_id}")
        
        # Include the list size in the response
        response = {
            'count': list_size,
            'users': results
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching users: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@internal_bp.route("/rank_articles_importance", methods=["GET"])
def rank_articles_importance():
    request_id = str(uuid.uuid4())
    logger.info(f"rank_articles_importance route - Request ID: {request_id}")
    try:
        # Get date parameters from query string
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")

        # Parse dates with defaults if not provided
        start_date = date_util.parse_iso_date(start_date_str) if start_date_str else datetime.now() - timedelta(days=1) 
        end_date = date_util.parse_iso_date(end_date_str) if end_date_str else datetime.now()

        # Fetch articles from user_feed table
        articles = user_feed_repo.get_articles_between_dates(start_date, end_date)
        if not articles:
            return jsonify({"message": "No articles found in the specified date range"}), 404

        # Prepare article summaries for LLM
        articles_text = "\n\n".join([
            f"Article ID: {article['article_id']}\nTitle: {article.get('title', 'No title')}\n"
            f"Summary: {article.get('summary_200', 'No summary')}"
            for article in articles
        ])

        # Prepare prompt for importance ranking
        prompt = """
        You are an expert news analyst. Review these articles and rank them by importance among each other
        on a scale of 1-100, considering:
        - Economic and business impact
        - Industry disruption potential
        - Scale (financial amounts, reach)
        - Relevance to key stakeholders
        - Timeliness and urgency

        Return only a valid JSON object with article IDs and scores without any prefix or suffix, in this format:
        {
            "article_rankings": [
                {"article_id": "id1", "importance_score": 75},
                {"article_id": "id2", "importance_score": 23}
            ]
        }
        """

        # Get rankings from LLM
        response = llm_util.chat_with_openai(articles_text, prompt)

        try:
            rankings = json.loads(response)
            logger.debug(f"Rankings: {rankings}")

            # Print article titles and importance scores for logging
            for ranking in rankings["article_rankings"]:
                article = next((a for a in articles if a["article_id"] == ranking["article_id"]), None)
                if article:
                    logger.info(f"Article: {article.get('title', 'No title')} - Importance Score: {ranking['importance_score']}")
            if not isinstance(rankings, dict) or "article_rankings" not in rankings:
                raise ValueError("Invalid response format")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error parsing LLM response: {str(e)} - Response: {response}")
            return jsonify({"error": "Failed to parse importance rankings"}), 500

        # Update articles with importance scores
        try:
            article_scores = [
                {
                    "article_id": ranking["article_id"],
                    "importance_score": ranking["importance_score"]
                }
                for ranking in rankings["article_rankings"]
            ]
            
            # Bulk update the user_feed table
            user_feed_repo.update_importance_scores(article_scores)

            return jsonify({
                "message": "Successfully updated importance scores",
                "articles_processed": len(article_scores),
                "rankings": rankings["article_rankings"]
            }), 200

        except Exception as e:
            logger.error(f"Error updating importance scores: {str(e)}")
            return jsonify({"error": "Failed to update importance scores"}), 500

    except Exception as e:
        logger.error(f"Error in rank_articles_importance: {str(e)}")
        return jsonify({"error": str(e)}), 500

@internal_bp.route("/create_audio", methods=["POST"])
def create_audio():
    request_id = str(uuid.uuid4())
    logger.info(f"create_audio route - Request ID: {request_id}")
    try:
        data = request.json
        if not data:
            raise BadRequest("No data received")

        # Validate required fields
        if "conversation" not in data:
            raise BadRequest("Missing required field: conversation")

        # Extract parameters
        conversation = data["conversation"]
        language = data.get("language", "en")  # Default to English if not specified
        add_background = data.get("add_background", False)  # Optional parameter

        # Generate audio segments
        audio_segment = podcaster.create_audio_segments(
            conversation=conversation,
            language=language,
            add_background=add_background
        )

        # Convert to bytes and prepare response
        audio_bytes = BytesIO()
        audio_segment.export(audio_bytes, format="mp3")
        audio_bytes.seek(0)

        return send_file(
            audio_bytes,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"audio_{request_id}.mp3",
        )

    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in create_audio_segments route: {str(e)}")
        return jsonify({"error": str(e)}), 500

from io import BytesIO
from flask import Blueprint, request, jsonify, g
from werkzeug.exceptions import BadRequest, Unauthorized
from lib.log import logger
from lib.auth import generate_token, verify_token, send_verification_email, generate_verification_code, revoke_token, is_token_about_to_expire, handle_token_refresh
from lib.validators import validate_email, validate_country, validate_language
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, decode_token, get_jwt, verify_jwt_in_request

from services import utilities, podcaster
from models.user import User
from db.factory import db_factory
from util import string_util, email_util
from routes.decorators import custom_jwt_required

user_bp = Blueprint('user', __name__)
user_repository = db_factory.get_user_repository()

@user_bp.route('/signup', methods=['POST'])
def signup():
    logger.info("signup route")
    return signin()

@user_bp.route('/signin', methods=['POST'])
def signin():
    logger.info("signin route")
    try:
        data = request.json
        email, first_name, country, language = validate_signin_data(data)
        
        user = user_repository.get_by_email(email)
        
        if not user:
            email_util.send_new_user_notification(email)
            return handle_new_user(email, first_name, country, language)
        
        if user.status == 'verified':
            if data:
                device_jti = data.get('device_jti')
                if device_jti and any(t['jti'] == device_jti for t in user.tokens):
                    return handle_verified_user(user, device_jti)

        # New device or no device_jti provided or unverified user. Treat as unverified user.
        return handle_unverified_user(user, email)
    except (BadRequest, Unauthorized) as e:
        return jsonify({
            "error": str(e),
            "message": "Authentication failed"
        }), 401
    except Exception as e:
        logger.error(f"Unexpected error in signin: {str(e)}")
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        }), 500

def validate_signin_data(data):
    email = data.get('email')
    first_name = data.get('first_name')
    country = data.get('country')
    language = data.get('language')

    if not all([email, first_name, country, language]):
        raise BadRequest("Missing required fields")

    if not validate_email(email):
        raise BadRequest("Invalid email format")

    if not validate_country(country):
        raise BadRequest("Invalid country code")

    if not validate_language(language):
        raise BadRequest("Invalid language code")

    return email.lower(), first_name.capitalize(), country.upper(), language.upper()

def handle_new_user(email, first_name, country, language):
    logger.debug(f"handle_new_user: {email}, {first_name}, {country}, {language}")
    user = User(email, first_name, country, language, verification_code=generate_verification_code())
    user_repository.add(user)

    logger.info(f"Sending verification email to {email}, with code {user.verification_code}")
    send_verification_email(email, user.verification_code)
    # Generate first intro audio in the same thread
    intro_audio = podcaster.get_or_create_first_intro_audio(user)
    # Generate rest of the intro audio files in the background
    utilities.background_task('services.podcaster.generate_intro_audio_files', user.first_name, user.id)

    return jsonify({"isNewUser": True, "verificationRequired": True, "message": "Verification code sent to email", "intro_audio": intro_audio}), 202

def handle_verified_user(user, device_jti=None):
    logger.debug(f"handle_verified_user: {user.email}")
    
    new_token, _ = generate_token(user.id, device_jti)
    
    intro_audio = podcaster.get_or_create_first_intro_audio(user)

    return jsonify({"token": new_token, "message": "Login successful", "intro_audio": intro_audio}), 200

def handle_unverified_user(user, email):
    logger.debug(f"Handling unverified user: {user.email}")
    user.verification_code = generate_verification_code()
    user.status = 'unverified'
    user_repository.update(user)
    
    logger.info(f"Sending verification email to {email}, with code {user.verification_code}")
    send_verification_email(email, user.verification_code)
    
    intro_audio = podcaster.get_or_create_first_intro_audio(user)

    return jsonify({"isNewUser": False, "verificationRequired": True, "message": "Verification code sent to email", "intro_audio": intro_audio}), 202

@user_bp.route('/verify', methods=['POST'])
def verify():
    logger.info("verify route")
    data = request.json
    if not data:
        raise BadRequest("Missing required fields")
    
    email = data.get('email')
    verification_code = data.get('verification_code')

    if not all([email, verification_code]):
        raise BadRequest("Missing required fields")

    user = user_repository.get_by_email(email)

    if not user:
        raise BadRequest("User not found")

    if user.verification_code != verification_code:
        raise BadRequest("Invalid verification code")

    user.status = 'verified'
    user.verification_code = None
    user_repository.update(user)

    utilities.background_task('services.podcaster.generate_intro_audio_files', user.first_name, user.id)
    utilities.background_task('services.user_feed.create_feeds_for_user', user.id)

    token, device_jti = generate_token(user.id)

    return jsonify({"token": token, "device_jti": device_jti, "message": "Email verified successfully", "user": _user_for_transport(user)}), 200

@user_bp.route('/generate_intro_audio', methods=['POST'])
def generate_intro_audio():
    logger.info("generate_intro_audio route")
    data = request.json
    if not data:
        raise BadRequest("Missing data")
    
    user_name = data.get('user_name')
    user_id = data.get('user_id')

    if not all([user_name, user_id]):
        raise BadRequest("Missing required fields")

    # Trigger background task to generate intro audio files
    utilities.background_task('services.podcaster.generate_intro_audio_files', user_name, user_id)

    return jsonify({"message": "Intro audio generation triggered"}), 202

@user_bp.route('/refresh_token', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    logger.info("refresh_token route")
    current_user = get_jwt_identity()
    new_token = create_access_token(identity=current_user)
    return jsonify({"token": new_token, "message": "Token refreshed successfully"}), 200

@user_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    logger.info("logout route")
    jwt = get_jwt()
    jti = jwt['jti']
    revoke_token(jti)
    return jsonify({"message": "Logged out successfully"}), 200

@user_bp.route('/logout_all', methods=['POST'])
@jwt_required()
def logout_all():
    logger.info("logout_all route")
    user_id = get_jwt_identity()
    revoke_token(user_id, all_tokens=True)
    return jsonify({"message": "Logged out from all devices successfully"}), 200

@user_bp.route('/verify_token', methods=['POST'])
@jwt_required()
def verify_token_endpoint():
    logger.info("verify_token route")
    try:
        user_id = get_jwt_identity()
        return jsonify({
            "valid": True,
            "user_id": user_id,
            "message": "Token is valid"
        }), 200
    except Exception as e:
        logger.error(f"Error verifying token: {str(e)}")
        return jsonify({
            "valid": False,
            "message": "Invalid token"
        }), 401

@user_bp.route('/update_preferences', methods=['POST'])
@custom_jwt_required()
def update_preferences():
    logger.info("update_preferences route")
    # Use user_id from kwargs if bypassed
    user_id = getattr(g, 'user_id', None) or get_jwt_identity()

    if not user_id:
        raise BadRequest("User ID not found")

    user = user_repository.get(user_id)
    if not user:
        raise BadRequest("User not found")

    data = request.json
    if not data:
        raise BadRequest("Missing preferences")
    
    # Preferences dict is flexible that it can handle any additional fields provided by the client
    # Add to special_fields for the fields that needs special handling, and everything else will be put in preferences dict
    preferences = {}
    special_fields = ['preferences_text', 'first_name', 'country', 'language', 'news_sources']
    
    # Handle all non-special fields
    for key, value in data.items():
        if key not in special_fields:
            preferences[key] = value
    
    # Convert preferences dict to text if not empty
    if preferences:
        preferences_text = str(preferences)
    else:
        preferences_text = data.get('preferences_text')
    
    first_name = data.get('first_name')
    country = data.get('country')
    language = data.get('language')
    news_sources = data.get('news_sources')
    
    trigger_feed_update = False

    if(first_name):
        # check if first name is a valid string with no special characters and atleast 3 characters
        if not first_name.isalpha() or len(first_name) < 3:
            raise BadRequest("Invalid first name")
        user.first_name = first_name
        utilities.background_task('services.podcaster.generate_intro_audio_files', first_name, user_id)
    if(country):
        try:
            country_name, country_code = validate_country(country)
            user.country = country_code
            user.country_name = country_name
        except ValueError as e:
            raise BadRequest(str(e))
    if(language):
        try:
            language_name, language_code = validate_language(language)
            user.language = language_code
            user.language_name = language_name
        except ValueError as e:
            raise BadRequest(str(e))

    if news_sources:
        if not hasattr(user, 'news_sources') or not isinstance(user.news_sources, list):
            user.news_sources = []  # Initialize as an empty list if not defined
        if isinstance(news_sources, list):
            for source in news_sources:
                domain = string_util.extract_domain(source)
                if domain and domain not in user.news_sources:  # Check if domain doesn't exist
                    user.news_sources.append(domain)
        else:
            domain = string_util.extract_domain(news_sources)
            if domain and domain not in user.news_sources:  # Check if domain doesn't exist
                user.news_sources.append(domain)
        trigger_feed_update = True

    if(first_name or country or language or news_sources):
        user_repository.update(user)

    if preferences_text:
        # Trigger background task to update user preferences
        utilities.background_task('services.user_management.update_user_preferences', user_id, preferences_text)

    # Trigger feed update only if there are no preferences_text provided
    # This is to avoid triggering feed update twice when preferences_text is provided
    if trigger_feed_update and not preferences_text:
        utilities.background_task('services.user_feed.create_feeds_for_user', user_id)

    return jsonify({"message": "Preferences update initiated"}), 202

def _user_for_transport(user):
    user_dict = user.to_dict()
    if user.intro_audio_urls:
        intro_audios = {key: utilities.generate_audio_url_public(url) for key, url in user.intro_audio_urls.items()}
        user_dict['intro_audio_urls'] = intro_audios
    user_dict.pop('verification_code')
    return user_dict
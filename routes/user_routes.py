from io import BytesIO
from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest, Unauthorized
from lib.log import logger
from lib.auth import generate_token, verify_token, send_verification_email, generate_verification_code, revoke_token, is_token_about_to_expire, handle_token_refresh
from lib.validators import validate_email, validate_country, validate_language
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, decode_token, get_jwt, verify_jwt_in_request

from services import utilities
from models.user import User
from db.factory import db_factory
from util import string_util

user_bp = Blueprint('user', __name__)
user_repository = db_factory.get_user_repository()

@user_bp.route('/signup', methods=['POST'])
def signup():
    logger.info("signup route")
    return signin()

@user_bp.route('/signin', methods=['POST'])
def signin():
    logger.info("signin route")
    data = request.json
    email, first_name, country, language, preferences = validate_signin_data(data)
    
    user = user_repository.get_by_email(email)
    
    if not user:
        return handle_new_user(email, first_name, country, language, preferences)
    
    if user.status == 'verified':
        if data:
            device_jti = data.get('device_jti')
            if device_jti and any(t['jti'] == device_jti for t in user.tokens):
                return handle_verified_user(user, preferences, device_jti)

    # New device or no device_jti provided or unverified user. Treat as unverified user.
    return handle_unverified_user(user, email, preferences)

def validate_signin_data(data):
    email = data.get('email')
    first_name = data.get('first_name')
    country = data.get('country')
    language = data.get('language')
    preferences = data.get('preferences')

    if not all([email, first_name, country, language]):
        raise BadRequest("Missing required fields")

    if not validate_email(email):
        raise BadRequest("Invalid email format")

    if not validate_country(country):
        raise BadRequest("Invalid country code")

    if not validate_language(language):
        raise BadRequest("Invalid language code")

    return email, first_name, country, language, preferences

def handle_new_user(email, first_name, country, language, preferences):
    logger.debug(f"handle_new_user: {email}, {first_name}, {country}, {language}, {preferences}")
    user = User(email, first_name, country, language, verification_code=generate_verification_code())
    user_repository.add(user)

    logger.info(f"Sending verification email to {email}, with code {user.verification_code}")
    send_verification_email(email, user.verification_code)
    utilities.background_task('services.podcaster.generate_intro_audio_files', user.first_name, user.id)

    if preferences:
        utilities.background_task('services.user_management.update_user_preferences', user.id, preferences)
    
    return jsonify({"isNewUser": True, "verificationRequired": True, "message": "Verification code sent to email"}), 202

def handle_verified_user(user, preferences, device_jti=None):
    logger.debug(f"handle_verified_user: {user.email}")
    
    new_token, _ = generate_token(user.id, device_jti)
    
    if preferences:
        utilities.background_task('services.user_management.update_user_preferences', user.id, preferences)
    
    return jsonify({"token": new_token, "message": "Login successful"}), 200

def handle_unverified_user(user, email, preferences):
    logger.debug(f"Handling unverified user: {user.email}")
    user.verification_code = generate_verification_code()
    user.status = 'unverified'
    user_repository.update(user)
    
    logger.info(f"Sending verification email to {email}, with code {user.verification_code}")
    send_verification_email(email, user.verification_code)
    
    if preferences:
        utilities.background_task('services.user_management.update_user_preferences', user.id, preferences)
    
    return jsonify({"isNewUser": False, "verificationRequired": True, "message": "Verification code sent to email"}), 202

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

    token, device_jti = generate_token(user.id)
    return jsonify({"token": token, "device_jti": device_jti, "message": "Email verified successfully"}), 200

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
@jwt_required()
def update_preferences():
    logger.info("update_preferences route")
    user_id = get_jwt_identity()

    if not user_id:
        raise BadRequest("User ID not found")

    user = user_repository.get(user_id)
    if not user:
        raise BadRequest("User not found")

    data = request.json
    if not data:
        raise BadRequest("Missing preferences")
    
    preferences_text = data.get('preferences')
    first_name = data.get('first_name')
    country = data.get('country')
    language = data.get('language')
    news_sources = data.get('news_sources')
    
    if(first_name):
        # check if first name is a valid string with no special characters and atleast 3 characters
        if not first_name.isalpha() or len(first_name) < 3:
            raise BadRequest("Invalid first name")
        user.first_name = first_name
    if(country):
        if not validate_country(country):
            raise BadRequest("Invalid country code")
        user.country = country
    if(language):
        if not validate_language(language):
            raise BadRequest("Invalid language code")
        user.language = language

    if news_sources:
        if not hasattr(user, 'news_sources') or not isinstance(user.news_sources, list):
            user.news_sources = []  # Initialize as an empty list if not defined
        if isinstance(news_sources, list):
            for source in news_sources:
                domain = string_util.extract_domain(source)
                if domain:
                    user.news_sources.append(domain)
        else:
            domain = string_util.extract_domain(news_sources)
            if domain:
                user.news_sources.append(domain)

    if(first_name or country or language or news_sources):
        user_repository.update(user)

    if not preferences_text:
        raise BadRequest("Missing preferences")

    # Trigger background task to update user preferences
    utilities.background_task('services.user_management.update_user_preferences', user_id, preferences_text)

    return jsonify({"message": "Preferences update initiated"}), 202


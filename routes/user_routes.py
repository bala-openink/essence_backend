from io import BytesIO
from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest
from lib.log import logger
from lib import db
from lib.auth import generate_token, verify_token, send_verification_email, generate_verification_code, revoke_token
from lib.validators import validate_email, validate_country, validate_language
import uuid

from services import utilities
from services.podcaster import generate_intro_audio_files

user_bp = Blueprint('user', __name__)

@user_bp.route('/signup', methods=['POST'])
def signup():
    logger.info("signup route")
    return signin()
    # Implement signup logic here
    pass

@user_bp.route('/signin', methods=['POST'])
def signin():
    logger.info("signin route")
    data = request.json
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

    user_table = db.get_user_table()
    user = user_table.get_user_by_email(email)

    if user and user['status'] == 'verified':
        token = generate_token(user['id'])
        return jsonify({"token": token, "message": "Signin successful"}), 200
    else:
        verification_code = generate_verification_code()
        if user:
            user['verification_code'] = verification_code
            user_table.addOrUpdate(user)
        else:
            user = {
                'id': str(uuid.uuid4()),
                'email': email,
                'first_name': first_name,
                'country': country,
                'language': language,
                'status': 'unverified',
                'verification_code': verification_code
            }
            user_table.add(user)

            # Trigger background task to generate intro audio files
            utilities.background_task(generate_intro_audio_files, user['first_name'], user['id'])


        logger.info(f"Sending the verification code: {verification_code}")
        # TODO: Integrate email service 
        send_verification_email(email, verification_code)
        return jsonify({"isNewUser": True, "message": "Verification code sent to email"}), 202

@user_bp.route('/verify', methods=['POST']) 
def verify():
    logger.info("verify route")
    data = request.json
    email = data.get('email')
    verification_code = data.get('verification_code')

    if not all([email, verification_code]):
        raise BadRequest("Missing required fields")

    user_table = db.get_user_table()
    user = user_table.get_user_by_email(email)

    if not user:
        raise BadRequest("User not found")

    if user['verification_code'] == verification_code:
        user['status'] = 'verified'
        user['verification_code'] = None
        user_table.addOrUpdate(user)
        token = generate_token(user['id'])

        # Trigger background task to generate intro audio files
        utilities.background_task(generate_intro_audio_files, user['first_name'], user['id'])

        return jsonify({"token": token, "firstName": user['first_name'], "message": "Email verified successfully"}), 200
    else:
        return jsonify({"message": "Invalid verification code"}), 400

@user_bp.route('/protected', methods=['GET'])
def protected():
    logger.info("protected route")
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        raise BadRequest("Missing Authorization header")

    token = auth_header.split(' ')[1]
    user_id = verify_token(token)

    if not user_id:
        raise BadRequest("Invalid or expired token")

    user_table = db.get_user_table()
    user = user_table.get(user_id)

    if not user:
        raise BadRequest("User not found")

    return jsonify({"message": "Access granted", "user": user}), 200

@user_bp.route('/generate_intro_audio', methods=['POST'])
def generate_intro_audio():
    logger.info("generate_intro_audio route")
    data = request.json
    user_name = data.get('user_name')
    user_id = data.get('user_id')

    if not all([user_name, user_id]):
        raise BadRequest("Missing required fields")

    # Trigger background task to generate intro audio files
    utilities.background_task(generate_intro_audio_files, user_name, user_id)

    return jsonify({"message": "Intro audio generation triggered"}), 202

@user_bp.route('/refresh_token', methods=['POST'])
def refresh_token():
    logger.info("refresh_token route")
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        raise BadRequest("Missing Authorization header")

    token = auth_header.split(' ')[1]
    user_id = verify_token(token)

    if not user_id:
        raise BadRequest("Invalid or expired token")

    new_token = generate_token(user_id)
    return jsonify({"token": new_token, "message": "Token refreshed successfully"}), 200

@user_bp.route('/logout', methods=['POST'])
def logout():
    logger.info("logout route")
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        raise BadRequest("Missing Authorization header")

    token = auth_header.split(' ')[1]
    user_id = verify_token(token)

    if not user_id:
        raise BadRequest("Invalid or expired token")

    revoke_token(token)
    return jsonify({"message": "Logged out successfully"}), 200

@user_bp.route('/logout_all', methods=['POST'])
def logout_all():
    logger.info("logout_all route")
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        raise BadRequest("Missing Authorization header")

    token = auth_header.split(' ')[1]
    user_id = verify_token(token)

    if not user_id:
        raise BadRequest("Invalid or expired token")

    revoke_token(user_id, all_tokens=True)
    return jsonify({"message": "Logged out from all devices successfully"}), 200

@user_bp.route('/verify_token', methods=['POST'])
def verify_token_endpoint():
    logger.info("verify_token route")
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"valid": False, "message": "Missing Authorization header"}), 401

    token = auth_header.split(' ')[1]
    user_id = verify_token(token)

    if user_id:
        return jsonify({"valid": True, "user_id": user_id, "message": "Token is valid"}), 200
    else:
        return jsonify({"valid": False, "message": "Invalid or expired token"}), 401


from io import BytesIO
from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest
from lib.log import logger
from lib import db
from lib.auth import generate_token, verify_token, send_verification_email, generate_verification_code
from lib.validators import validate_email, validate_country, validate_language
import uuid

from services import podcaster, utilities

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
            user_table.update_user(user['id'], {'verification_code': verification_code})
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
        # send_verification_email(email, verification_code)
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

        return jsonify({"token": token, "message": "Email verified successfully"}), 200
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

# Add more user-related routes as needed
def generate_intro_audio_files(user_name, user_id):
    try:
        user_table = db.get_user_table()
        user = user_table.get(user_id)
        if not user:
            raise BadRequest("User not found")

        # If user doesn't have intro_audio_urls, generate them
        if not user.get('intro_audio_urls'):
            combinations = [
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "morning"},
            {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "afternoon"},
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "evening"},
                {"is_first_time_ever": True, "is_first_time_today": True, "time_of_day": "day"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "morning"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "afternoon"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "evening"},
                {"is_first_time_ever": False, "is_first_time_today": True, "time_of_day": "day"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "morning"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "afternoon"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "evening"},
                {"is_first_time_ever": False, "is_first_time_today": False, "time_of_day": "day"},
            ]

            audio_urls = {}

            for combo in combinations:
                intro_segment = podcaster.generate_intro_audio(
                    userName=user_name,
                    isFirstTimeEver=combo["is_first_time_ever"],
                    isFirstTimeToday=combo["is_first_time_today"],
                    timeOfDay=combo["time_of_day"],
                    twoSpeakers=True
                )

                intro_audio = BytesIO()
                intro_segment.export(intro_audio, format="mp3")
                intro_audio.seek(0)

                key = f"{combo['is_first_time_ever']}_{combo['is_first_time_today']}_{combo['time_of_day']}"
                s3_key = f"{user_id}/intro/{key}"
                s3_url = utilities.upload_audio_to_s3(s3_key, intro_audio)
                audio_urls[key] = s3_url
                logger.info(f"Created intro audio file for {s3_key} and uploaded to {s3_url}")

            # Update the user table with the audio URLs
            user["intro_audio_urls"] = audio_urls
            db.get_user_table().addOrUpdate(user)

    except Exception as e:
        logger.error(f"Error generating intro audio files: {str(e)}", exc_info=True)
from flask_jwt_extended import create_access_token, decode_token, get_jwt_identity
from datetime import datetime, timedelta
import uuid
from util.email_util import send_email
from services import utilities
from lib.log import logger
from config import JWT_EXPIRATION_DELTA
import random
import string
from db.factory import db_factory

user_repository = db_factory.get_user_repository()

def generate_token(user_id, jti=None):
    jti = jti or str(uuid.uuid4())
    expiration_time = datetime.utcnow() + timedelta(seconds=int(JWT_EXPIRATION_DELTA))
    additional_claims = {
        'jti': jti
    }
    token = create_access_token(identity=user_id, additional_claims=additional_claims, expires_delta=timedelta(seconds=int(JWT_EXPIRATION_DELTA)))
    
    # Store the token in the user table
    user = user_repository.get(user_id)
    if user:
        token_data = {'jti': jti, 'created_at': datetime.utcnow().isoformat(), 'expires_at': expiration_time.isoformat()}
        user_repository.add_token(user_id, token_data)
    
    return token, jti

def verify_token(token):
    try:
        decoded_token = decode_token(token)
        user_id = decoded_token['sub']
        exp = datetime.fromtimestamp(decoded_token['exp'])
        jti = decoded_token['jti']
        user = user_repository.get(user_id)
        if user and any(t['jti'] == jti for t in user.tokens):
            return user_id, exp, jti
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
    return None, None, None

def revoke_token(token, all_tokens=False):
    try:
        decoded_token = decode_token(token, allow_expired=True)
        user_id = decoded_token['sub']
        jti = decoded_token['jti']
        
        if all_tokens:
            user_repository.remove_all_tokens(user_id)
        else:
            user_repository.remove_token(user_id, jti)
    except Exception as e:
        logger.error(f"Error revoking token: {e}")

def generate_verification_code():
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, verification_code):
    subject = "Email Verification for 'essence'"
    body = f"Hello,\n\nThank you for registering with 'essence'. Your verification code is: {verification_code}\n\nBest regards,\nThe 'essence' Team"
    send_email(email, subject, body)

def is_token_about_to_expire(token, threshold_seconds=86400):  # 24 hours
    try:
        decoded_token = decode_token(token)
        expiration_time = datetime.fromtimestamp(decoded_token['exp'])
        time_until_expiration = expiration_time - datetime.utcnow()
        return time_until_expiration.total_seconds() <= threshold_seconds
    except Exception as e:
        logger.error(f"Error checking token expiration: {e}")
        return False

def handle_token_refresh(user_id, existing_token, device_jti=None):
    user = user_repository.get(user_id)
    if not user:
        return None, "User not found"

    if existing_token:
        user_id, expiration_time, token_jti = verify_token(existing_token)
        if user_id and (not device_jti or device_jti == token_jti):
            if is_token_about_to_expire(existing_token):
                new_token, _ = generate_token(user_id, device_jti)
                return new_token, "Token refreshed"
            else:
                return existing_token, "Existing token is valid"
        else:
            # Token expired, send verification code
            verification_code = generate_verification_code()
            user.verification_code = verification_code
            user.status = 'unverified'
            user_repository.update(user)
            logger.info(f"Sending verification email to {user.email}, with code {verification_code}")
            send_verification_email(user.email, verification_code)
            return None, "Token expired. Verification code sent to email"
    
    new_token, _ = generate_token(user_id, device_jti)
    return new_token, "New token generated"

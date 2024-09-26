import jwt
import datetime
import uuid
import random
import string
from lib.email_service import send_email
from services import utilities
from lib.log import logger
from lib import db

JWT_SECRET_KEY = utilities.get_secret('JWT_SECRET_KEY', 'temp-key')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_DELTA = utilities.get_secret('JWT_EXPIRATION_DELTA', 86400)

def generate_token(user_id):
    jti = str(uuid.uuid4())
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=int(JWT_EXPIRATION_DELTA)),
        'jti': jti
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    # Store the token in the user table
    user_table = db.get_user_table()
    user = user_table.get(user_id)
    if not user.get('tokens'):
        user['tokens'] = []
    user['tokens'].append({'jti': jti, 'created_at': datetime.datetime.utcnow().isoformat()})
    db.get_user_table().addOrUpdate(user)
    
    return token

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_table = db.get_user_table()
        user = user_table.get(payload['user_id'])
        if user and any(t['jti'] == payload['jti'] for t in user.get('tokens', [])):
            return payload['user_id']
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
    return None

def revoke_token(token, all_tokens=False):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload['user_id']
        jti = payload['jti']
        
        user_table = db.get_user_table()
        user = user_table.get(user_id)
        if user:
            if all_tokens:
                user['tokens'] = []
            else:
                user['tokens'] = [t for t in user.get('tokens', []) if t['jti'] != jti]
            db.get_user_table().addOrUpdate(user)
    except Exception as e:
        logger.error(f"Error revoking token: {e}")

def generate_verification_code():
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, verification_code):
    subject = "Email Verification for 'essence'"
    body = f"Hello,\n\nThank you for registering with 'essence'. Your verification code is: {verification_code}\n\nBest regards,\nThe 'essence' Team"
    send_email(email, subject, body)
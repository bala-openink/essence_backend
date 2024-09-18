import jwt
import datetime
import random
import string
from lib.email_service import send_email
from services import utilities

JWT_SECRET_KEY = utilities.get_secret('JWT_SECRET_KEY', 'temp-key')
JWT_ALGORITHM = utilities.get_secret('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_DELTA = utilities.get_secret('JWT_EXPIRATION_DELTA', 3600)

def generate_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=int(JWT_EXPIRATION_DELTA))
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def generate_verification_code():
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, verification_code):
    subject = "Email Verification for 'essence'"
    body = f"Hello,\n\nThank you for registering with 'essence'. Your verification code is: {verification_code}\n\nBest regards,\nThe 'essence' Team"
    send_email(email, subject, body)
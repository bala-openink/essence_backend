from functools import wraps
from flask import request, jsonify, g
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from db.factory import db_factory
import constants
from services import utilities

user_repository = db_factory.get_user_repository()

CUSTOM_HEADER_NAME = constants.INTERNAL_API_KEY_HEADER
CUSTOM_HEADER_VALUE = utilities.get_secret(secret_key='INTERNAL_API_KEY', default_value="essence-local")

def custom_jwt_required(optional=False, fresh=False, refresh=False, locations=None, verify_type=True, skip_revocation_check=False):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            # Check for internal test header
            if request.headers.get(CUSTOM_HEADER_NAME) == CUSTOM_HEADER_VALUE:
                # Get email from either query params (GET) or request body (POST)
                email = request.args.get('email') if request.method == 'GET' else request.json.get('email')
                if not email:
                    return jsonify({"message": "Email required for internal testing"}), 400
                
                user = None
                if email:
                    user = user_repository.get_by_email(email)
                
                if not user:
                    return jsonify({"message": "User not found"}), 404
                
                # Set user_id in g for use in the endpoint
                g.user_id = user.id
                return fn(*args, **kwargs)

            # Proceed with normal JWT verification
            verify_jwt_in_request(optional, fresh, refresh, locations, verify_type, skip_revocation_check)
            return fn(*args, **kwargs)
        return decorator
    return wrapper

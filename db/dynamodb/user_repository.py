from typing import List, Optional, Dict, Any
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from lib.log import logger
from ..interfaces.database import UserRepository
from .repository import DynamoDBRepository
from models.user import User

class DynamoDBUserRepository(UserRepository):
    """DynamoDB implementation of UserRepository"""

    def __init__(self, table):
        self._table = table
        self._base_repo = DynamoDBRepository(table)

    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        user_dict = self._base_repo.get(user_id)
        return User.from_dict(user_dict) if user_dict else None

    def add(self, user: User) -> Optional[User]:
        """Add new user"""
        user_dict = user.to_dynamo_dict()
        result = self._base_repo.add(user_dict)
        return User.from_dict(result) if result else None

    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email using EmailIndex"""
        result = self._table.query(
            IndexName='EmailIndex',
            KeyConditionExpression=Key('email').eq(email)
        ).get('Items', [])
        
        # Return None if no items found, otherwise convert first item to User
        return User.from_dict(result[0]) if result else None

    def update(self, user: User) -> Optional[User]:
        """Update existing user"""
        user_dict = user.to_dynamo_dict()
        result = self._base_repo.update(user_dict)
        return User.from_dict(result) if result else None

    def get_verified_users(self) -> List[User]:
        """Get all verified users"""
        try:
            response = self._table.scan(
                FilterExpression=Attr('status').eq('verified')
            )
            users = response.get('Items', [])
            return [User.from_dict(user_dict) for user_dict in users]
        except ClientError as e:
            logger.error(f"Error getting verified users from DynamoDB: {e}")
            return []

    def update_preferences(self, user_id: str, preferences: Dict) -> bool:
        """Update user preferences"""
        return self.update_field(user_id, 'preferences', preferences)

    def add_token(self, user_id: str, token_data: Dict) -> bool:
        """Add authentication token to user"""
        return self.update_field(user_id, 'tokens', token_data, is_list_append=True)

    def remove_token(self, user_id: str, jti: str) -> bool:
        """Remove specific token from user"""
        try:
            user = self.get(user_id)
            if not user or not hasattr(user, 'tokens'):
                logger.error(f"User not found or has no tokens for ID: {user_id}")
                return False
            
            tokens = [t for t in user.tokens if t.get('jti') != jti]
            return self.update_field(user_id, 'tokens', tokens)
        except ClientError as e:
            logger.error(f"Error removing token from user in DynamoDB: {e}")
            return False

    def remove_all_tokens(self, user_id: str) -> bool:
        """Remove all tokens from user"""
        return self.update_field(user_id, 'tokens', [])

    def update_status(self, user_id: str, status: str) -> bool:
        """Update user status"""
        return self.update_field(user_id, 'status', status)

    def list_by_status(self, status: str) -> List[User]:
        """List users by status"""
        try:
            response = self._table.scan(
                FilterExpression=Attr('status').eq(status)
            )
            users = response.get('Items', [])
            return [User.from_dict(user_dict) for user_dict in users]
        except ClientError as e:
            logger.error(f"Error listing users by status from DynamoDB: {e}")
            return []

    def update_field(self, user_id: str, field: str, value: Any, is_list_append: bool = False) -> bool:
        """Generic method to update a single field"""
        try:
            if not self.get(user_id):
                logger.error(f"User not found for ID: {user_id}")
                return False
            
            if is_list_append:
                update_expr = f'SET {field} = list_append(if_not_exists({field}, :empty_list), :value)'
                expr_values = {':value': [value], ':empty_list': []}
            else:
                update_expr = f'SET {field} = :value'
                expr_values = {':value': value}

            self._table.update_item(
                Key={'id': user_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
            return True
        except ClientError as e:
            logger.error(f"Error updating {field} in DynamoDB: {e}")
            return False

    def delete(self, user_id: str) -> bool:
        """Delete user by ID"""
        return self._base_repo.delete(user_id)



from typing import Optional, List, Dict, Any, TypeVar, Generic
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr

from lib.log import logger
from ..interfaces.database import GenericRepository

T = TypeVar('T', bound=Dict[str, Any])

class DynamoDBRepository(GenericRepository[T]):
    """Generic DynamoDB repository implementation"""

    def __init__(self, table):
        self._table = table

    def get(self, id: str) -> Optional[T]:
        """Get item by ID"""
        try:
            response = self._table.get_item(Key={'id': id})
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Error getting item from DynamoDB: {e}")
            return None

    def add(self, item: T) -> Optional[T]:
        """Add new item"""
        try:
            if not item:
                raise ValueError('Item empty')
            self._table.put_item(Item=item)
            return item
        except (ClientError, ValueError) as e:
            logger.error(f"Error adding item to DynamoDB: {e}")
            return None

    def delete(self, id: str) -> bool:
        """Delete item by ID"""
        try:
            self._table.delete_item(Key={'id': id})
            return True
        except ClientError as e:
            logger.error(f"Error deleting item from DynamoDB: {e}")
            return False

    def list(self, **kwargs) -> List[T]:
        """List items with optional filters"""
        try:
            if kwargs:
                filter_expressions = []
                expr_attr_names = {}
                expr_attr_values = {}
                
                for key, value in kwargs.items():
                    filter_expressions.append(f'#{key} = :{key}')
                    expr_attr_names[f'#{key}'] = key
                    expr_attr_values[f':{key}'] = value
                    
                scan_params = {
                    'FilterExpression': ' AND '.join(filter_expressions),
                    'ExpressionAttributeNames': expr_attr_names,
                    'ExpressionAttributeValues': expr_attr_values
                }
            else:
                scan_params = {}
                
            response = self._table.scan(**scan_params)
            return response['Items']
        except ClientError as e:
            logger.error(f"Error listing items from DynamoDB: {e}")
            return []

    def update(self, item: T) -> Optional[T]:
        """Update existing item"""
        try:
            if not item or 'id' not in item:
                raise ValueError('Invalid item for update')
                
            existing_item = self.get(item['id'])
            if existing_item:
                existing_item.update(item)
                self._table.put_item(Item=existing_item)
                return existing_item
            else:
                return self.add(item)
        except (ClientError, ValueError) as e:
            logger.error(f"Error updating item in DynamoDB: {e}")
            return None

    def query(self, **kwargs) -> Dict[str, Any]:
        """Execute a query with the provided parameters"""
        try:
            response = self._table.query(**kwargs)
            return response
        except ClientError as e:
            logger.error(f"Error querying DynamoDB: {e}")
            raise

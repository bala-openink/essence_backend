import datetime
from typing import Optional, Dict, Any, TypeVar
from botocore.exceptions import ClientError

from lib.log import logger
from ..interfaces.database import FeedBatchRepository

T = TypeVar('T', bound=Dict[str, Any])

class DynamoDBFeedBatchRepository(FeedBatchRepository):
    """DynamoDB implementation of feed batch operations"""

    def __init__(self, table):
        self._table = table

    def get_batch(self, batch_id: str) -> Optional[Dict]:
        try:
            response = self._table.get_item(Key={'id': batch_id})
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Error getting batch from DynamoDB: {e}")
            return None

    def create_batch(self, batch_record: Dict) -> Optional[Dict]:
        try:
            self._table.put_item(Item=batch_record)
            return batch_record
        except ClientError as e:
            logger.error(f"Error creating batch in DynamoDB: {e}")
            return None

    def update_batch_status(
        self,
        batch_id: str,
        stage: str,
        result: Optional[Dict] = None,
        error_msg: Optional[str] = None
    ) -> bool:
        try:
            if batch_id is None:
                return False

            update_parts = []
            expr_values = {}
            expr_names = {'#s': stage}

            # For stage1, increment completed_feeds
            if stage == 'stage1':
                update_parts.append('completed_feeds = if_not_exists(completed_feeds, :zero) + :one')
                expr_values[':zero'] = 0
                expr_values[':one'] = 1

            # Update stage stats
            if result:
                update_parts.append('#s = :stats')
                expr_values[':stats'] = {
                    'processed': result.get('processed', 0),
                    'skipped': result.get('skipped', 0),
                    'errors': result.get('errors', [])
                }

            # Add error
            if error_msg:
                error_info = {
                    'error': error_msg,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                if not result:
                    update_parts.append('#s = :init')
                    expr_values[':init'] = {
                        'processed': 0,
                        'skipped': 0,
                        'errors': [error_info]
                    }
                else:
                    update_parts.append('#s.errors = list_append(#s.errors, :error)')
                    expr_values[':error'] = [error_info]

            if update_parts:
                self._table.update_item(
                    Key={'id': batch_id},
                    UpdateExpression='SET ' + ', '.join(update_parts),
                    ExpressionAttributeNames=expr_names,
                    ExpressionAttributeValues=expr_values
                )
            return True

        except ClientError as e:
            logger.error(f"Error updating batch status in DynamoDB: {e}")
            return False

    def mark_stage_complete(
        self,
        batch_id: str,
        stage: str,
        end_time: str
    ) -> bool:
        try:
            if batch_id is None:
                return False
            self._table.update_item(
                Key={'id': batch_id},
                UpdateExpression=f'SET {stage}_status = :done, {stage}_end_time = :end',
                ExpressionAttributeValues={
                    ':done': 'completed',
                    ':end': end_time
                }
            )
            return True
        except ClientError as e:
            logger.error(f"Error marking stage complete in DynamoDB: {e}")
            return False
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
            update_expr = []
            expr_values = {}

            if batch_id is None:
                return False
            
            if stage == 'stage1':
                update_expr.append('SET completed_feeds = completed_feeds + :one')
                expr_values[':one'] = 1

                if result:
                    update_expr.extend([
                        'results.total_articles = results.total_articles + :p',
                        'results.total_skipped = results.total_skipped + :s'
                    ])
                    expr_values.update({
                        ':p': result.get('processed', 0),
                        ':s': result.get('skipped', 0)
                    })

                    if result.get('errors'):
                        update_expr.append('results.error_articles = list_append(if_not_exists(results.error_articles, :empty), :errors)')
                        expr_values.update({
                            ':errors': result['errors'],
                            ':empty': []
                        })

            else:  # stage2 or stage3
                if result:
                    update_expr.extend([
                        f'{stage}.processed = if_not_exists({stage}.processed, :zero) + :p',
                        f'{stage}.skipped = if_not_exists({stage}.skipped, :zero) + :s'
                    ])
                    expr_values.update({
                        ':p': result.get('processed', 0),
                        ':s': result.get('skipped', 0),
                        ':zero': 0
                    })

            if error_msg:
                error_info = {
                    'error': error_msg,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                update_expr.append(f'{stage}.errors = list_append(if_not_exists({stage}.errors, :empty), :errors)')
                expr_values.update({
                    ':errors': [error_info],
                    ':empty': []
                })

            if update_expr:
                self._table.update_item(
                    Key={'id': batch_id},
                    UpdateExpression=', '.join(update_expr),
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
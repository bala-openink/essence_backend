from flask import Blueprint, request, jsonify
from lib.log import logger
from lib import db
import uuid

test_bp = Blueprint('test', __name__)

##################################################################################
# ######## TESTING ENDPOINTS #####################################################
##################################################################################

@test_bp.route('/test/articles', methods=['GET'])
def test_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"test_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=None, type=int)
        all_attributes = request.args.get('all_attributes', default='false').lower() == 'true'

        table = db.get_article_table()
        items = table.list()

        # Extract desired fields
        results = []
        for item in items:
            if all_attributes:
                result = item.copy()
                if 'full_text' in result:
                    # Trim full_text to 50 words
                    result['full_text'] = ' '.join(result['full_text'].split()[:50]) + '...'
            else:
                result = {
                    'id': item.get('id'),
                    'title': item.get('title'),
                    'url': item.get('url'),
                    'processing_status': item.get('processing_status'),
                    'date_published': item.get('date_published')
                }
            results.append(result)

        # Apply limit if specified
        if limit is not None:
            results = results[:limit]

        list_size = len(results)
        logger.info(f"Fetched {list_size} articles from DynamoDB - Request ID: {request_id}")
        
        # Include the list size in the response
        response = {
            'count': list_size,
            'articles': results
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500

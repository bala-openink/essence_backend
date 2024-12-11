from io import StringIO
import csv
from typing import List, Dict

def articles_to_csv(articles: List[Dict], request_id: str) -> tuple[str, str]:
    """
    Convert a list of articles to CSV format.
    
    Args:
        articles (List[Dict]): List of article dictionaries
        request_id (str): Request ID for filename generation
        
    Returns:
        tuple: (csv_string, filename)
    """
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['date_created', 'public_key', 'title', 'domain', 'categories'])
    
    # Write article data
    for article in articles:
        writer.writerow([
            article.get('date_created', ''),
            article.get('public_key') or article.get('id', ''),
            article.get('title', ''),
            article.get('domain', ''),
            ','.join(str(cat) for cat in article.get('categories', []))
        ])
    
    output.seek(0)
    csv_content = output.getvalue()
    filename = f'articles_{request_id}.csv'
    
    return csv_content, filename

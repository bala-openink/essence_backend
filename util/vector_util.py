import numpy as np
from util import llm_util
from lib.log import logger
import datetime

# Compute the cosine similarity matrix for a given matrix A
def cosine_similarity(A):
    # Compute the dot product
    dot_product = np.dot(A, A.T)
    
    # Compute the norms
    norms = np.linalg.norm(A, axis=1)
    
    # Compute the cosine similarity
    cosine_sim = dot_product / np.outer(norms, norms)
    
    # Ensure the diagonal is exactly 1 (to handle numerical precision issues)
    np.fill_diagonal(cosine_sim, 1.0)
    
    return cosine_sim

# Compute the cosine similarity between two vectors
def cosine_similarity_vector(A, B):
    # Convert potential Decimal values from DynamoDB to float numpy array
    A = np.array(A, dtype=np.float64)
    B = np.array(B, dtype=np.float64)
    
    dot_product = np.dot(A, B)
    norm_A = np.linalg.norm(A)
    norm_B = np.linalg.norm(B)
    return dot_product / (norm_A * norm_B)

def create_flat_embedding(text):
    logger.debug(f"create_flat_embedding >> Text :: {text}")
    embedding = llm_util.get_base_embedding(text)
    embedding = embedding / np.linalg.norm(embedding)
    logger.debug(f"create_flat_embedding >> Embedding :: {embedding.shape}")
    return embedding

def create_user_embedding(json_structure):
    logger.debug(f"create_user_embedding >> Json Structure :: {json_structure}")
    dimension_vectors = []
    for dimension, prefs in json_structure.items():
        pos_embeddings = generate_weighted_embeddings(prefs["values"], prefs["priority_order"], dimension)
        neg_embeddings = generate_weighted_embeddings(prefs["exclude_values"], prefs["priority_order"], dimension)
        
        dimension_vector = combine_embeddings(pos_embeddings, neg_embeddings)
        dimension_vector = dimension_vector / np.linalg.norm(dimension_vector)

        dimension_vectors.append(dimension_vector)
    
    user_embedding = np.mean(dimension_vectors, axis=0)
    user_embedding = user_embedding / np.linalg.norm(user_embedding)
    logger.debug(f"create_user_embedding >> User Embedding :: {user_embedding.shape}")
    return user_embedding

def generate_weighted_embeddings(values, priority_order, dimension):
    embeddings = {}
    for index, value in enumerate(values):
        context = f"{dimension}: {value}"
        embedding = llm_util.get_base_embedding(context)
        if priority_order:
            weight = (len(values) - index) / len(values)
            embedding *= weight
        embeddings[value] = embedding
    return embeddings

def combine_embeddings(positive_embeddings, negative_embeddings):
    positive_vector = np.sum(list(positive_embeddings.values()), axis=0)
    negative_vector = np.sum(list(negative_embeddings.values()), axis=0)
    combined_vector = positive_vector - negative_vector
    return combined_vector

def deduplicate_articles(articles):
    if not articles:
        return [], []

    start_time = datetime.datetime.now()
    logger.info(f"Starting deduplication process with {len(articles)} articles at {start_time}")

    vectors = np.array([article.get('summary_vector') for article in articles])
    similarity_matrix = cosine_similarity(vectors)
    
    duplicate_articles = []
    original_articles = set(range(len(articles)))

    for i in range(len(articles)):
        if i in original_articles:
            for j in range(i + 1, len(articles)):
                if j in original_articles and similarity_matrix[i][j] > 0.80:
                    logger.debug(f"Duplicate found: {articles[i]['title']} and {articles[j]['title']} with similarity {similarity_matrix[i][j]:.4f}")
                    # Store only essential fields for duplicate article
                    if articles[i]['date_published'] < articles[j]['date_published']:
                        duplicate_articles.append({
                            'id': articles[i]['id'],
                            'status': 'duplicate_article',
                            'comments': f"duplicate of {articles[j]['id']}"
                        })
                        original_articles.remove(i)
                        logger.debug(f"Marked older article as duplicate: {articles[i]['id']}")
                        break
                    else:
                        duplicate_articles.append({
                            'id': articles[j]['id'],
                            'status': 'duplicate_article',
                            'comments': f"duplicate of {articles[i]['id']}"
                        })
                        original_articles.remove(j)
                        logger.debug(f"Marked newer article as duplicate: {articles[j]['id']}")

    end_time = datetime.datetime.now()
    logger.info(f"Deduplication complete. Found {len(duplicate_articles)} duplicates. {len(original_articles)} articles remaining. Took {end_time - start_time} seconds.")
    deduplicated_articles = [articles[i] for i in original_articles]
    
    return duplicate_articles, deduplicated_articles

def sort_by_preference_vector(articles, preference_vector, descending=True):
    """
    Sort articles based on cosine similarity between their summary vectors and user preference vector.
    
    Args:
        articles: List of article objects with summary_vector attribute
        preference_vector: User's preference vector
        
    Returns:
        List of articles sorted by descending similarity score
    """
    # Calculate cosine similarity and add score to each article
    try:
        for article in articles:
            article['score'] = float(cosine_similarity_vector(article.get('summary_vector'), preference_vector))
    except Exception as e:
        logger.error(f"Error in sort_by_preference_vector: {str(e)}")
        raise
    
    # Sort by score in descending order
    return sorted(articles, key=lambda x: x.get('score'), reverse=descending)

# External imports
import numpy as np
from services.openai_service import openai_service
import datetime

# Project imports
from util import llm_util
from lib.log import logger
import constants


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
    embedding = get_base_embedding(text)
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
        embedding = get_base_embedding(context)
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
                if j in original_articles and similarity_matrix[i][j] > 0.85:
                    logger.info(f"Duplicate found: {articles[i]['title']} and {articles[j]['title']} with similarity {similarity_matrix[i][j]:.4f}")
                    # Store only essential fields for duplicate article
                    if articles[i]['date_published'] < articles[j]['date_published']:
                        duplicate_articles.append({
                            'id': articles[i]['id'],
                            'processing_status': 'duplicate_article',
                            'comments': f"duplicate of {articles[j]['id']}"
                        })
                        original_articles.remove(i)
                        logger.debug(f"Marked older article as duplicate: {articles[i]['id']}")
                        break
                    else:
                        duplicate_articles.append({
                            'id': articles[j]['id'],
                            'processing_status': 'duplicate_article',
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

# Embed the user preferences and normalize it - Entry point for user embeddings
def get_user_embedding_with_weights(user_preferences, user, model="text-embedding-3-small"):
    start_time = datetime.datetime.now()
    logger.info(f"Starting user embedding generation at {start_time}")
    try:
        # Define weights for known dimensions
        weighted_dimensions = {
            'industry': 0.1,
            'industries': 0.2,
            'regions': 0.2,
            'functions': 0.2
        }
        
        final_embedding = np.zeros(constants.EMBEDDING_DIMENSION)
        content_weight = 0.3
        
        # Process all dimensions generically
        all_values = []
        for dim_name, dim_data in user_preferences.items():
            # Skip metadata fields that end with _order or _exclusions
            if dim_name.endswith('_order') or dim_name.endswith('_exclusions'):
                continue
                
            values = dim_data if isinstance(dim_data, list) else []
            order_key = f"{dim_name}_order"
            excl_key = f"{dim_name}_exclusions"
            
            priority_order = user_preferences.get(order_key, False)
            exclusions = user_preferences.get(excl_key, [])
            
            # Get embedding for this dimension
            dim_embedding = get_dimension_embedding(values, exclusions, priority_order, model)
            
            if len(dim_embedding) > 0:
                # Apply special weighting if it's a known dimension
                if dim_name in weighted_dimensions:
                    final_embedding += dim_embedding * weighted_dimensions[dim_name]
                
                # Collect values for combined content embedding
                all_values.extend(values)
        
        # Add user's country to the region dimension if available
        if user.country_name:
            region_embedding = get_base_embedding(user.country_name, model)
            final_embedding += region_embedding * weighted_dimensions['regions']
        
        # Add content embedding from all values combined
        if all_values:
            content_text = " ".join(all_values)
            content_embedding = get_base_embedding(content_text, model)
            final_embedding += content_embedding * content_weight
            
        # Normalize the final embedding if it's not all zeros
        if not np.all(final_embedding == 0):
            final_embedding = final_embedding / np.linalg.norm(final_embedding)
            
        end_time = datetime.datetime.now()
        logger.info(f"User embedding generation completed at {end_time}. Took {end_time - start_time} seconds.")
        return final_embedding
    except Exception as e:
        logger.error(f"Error in user weighted embedding generation: {str(e)}")
        return np.array([])

# Helper function to get weighted embeddings for a dimension
def get_dimension_embedding(values, exclusions=None, priority_order=False, model="text-embedding-3-small"):
    if not values:
        return np.array([])
        
    # Handle positive embeddings with priority weights if needed
    pos_embeddings = []
    for idx, value in enumerate(values):
        embedding = get_base_embedding(value, model)
        if priority_order:
            # Apply decreasing weights based on position
            weight = (len(values) - idx) / len(values)
            embedding *= weight
        pos_embeddings.append(embedding)
    
    # Combine positive embeddings
    pos_vector = np.mean(pos_embeddings, axis=0) if pos_embeddings else np.array([])
    
    # Handle exclusions if any
    if exclusions:
        neg_embeddings = [get_base_embedding(val, model) for val in exclusions]
        neg_vector = np.mean(neg_embeddings, axis=0) if neg_embeddings else np.array([])
        # Subtract negative embeddings from positive
        if len(pos_vector) > 0 and len(neg_vector) > 0:
            return pos_vector - neg_vector
    
    return pos_vector if len(pos_vector) > 0 else np.array([])

# Embed the article summary and normalize it - Entry point for article embeddings
def get_article_embedding_normalized(article, model="text-embedding-3-small"):
    if not article:
        return np.array([])
    
    embedding = get_article_embedding_with_weights(article.get("summary_200"), article.get("region"), article.get("categories"),
                                            article.get("industry"), article.get("function"), model)
    embedding_array = np.array(embedding)
    if np.all(embedding_array == 0):
        return embedding_array
    return embedding_array / np.linalg.norm(embedding_array)

def get_article_embedding_with_weights(text, region=None, categories=None, industry=None, function=None, model="text-embedding-3-small"):
    try:
        # Get separate embeddings for each component
        content_embedding = get_base_embedding(text, model)
        
        # Initialize weights (these could be tuned)
        content_weight = 0.5
        region_weight = 0.1
        industry_weight = 0.2
        function_weight = 0.1
        category_weight = 0.1
        
        final_embedding = content_embedding * content_weight
        
        if region:
            region_embedding = get_base_embedding(region, model)
            final_embedding += region_embedding * region_weight
            
        if categories:
            # Get embedding for each category separately
            category_embeddings = [get_base_embedding(cat, model) for cat in categories]
            avg_category_embedding = np.mean(category_embeddings, axis=0)
            final_embedding += avg_category_embedding * category_weight
        
        if industry:
            industry_embedding = get_base_embedding(industry, model)
            final_embedding += industry_embedding * industry_weight
            
        if function:
            function_embedding = get_base_embedding(function, model)
            final_embedding += function_embedding * function_weight
            
        # Normalize the final embedding
        return final_embedding / np.linalg.norm(final_embedding)
    except Exception as e:
        logger.error(f"Error in weighted embedding generation: {str(e)}")
        return np.array([])

def get_base_embedding(text, model="text-embedding-3-small"):
    try:
        response = openai_service.client.embeddings.create(
            input=[text.replace("\n", " ")], 
            model=model
        )
        return np.array(response.data[0].embedding)
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        return np.array([])


def get_embedding_for_text(text, model="text-embedding-3-small"):
    embedding = get_base_embedding(text, model)
    return np.array(embedding) / np.linalg.norm(np.array(embedding))


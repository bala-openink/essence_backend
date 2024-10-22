import numpy as np
from util import llm_util
from lib.log import logger

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
    dot_product = np.dot(A, B)
    norm_A = np.linalg.norm(A)
    norm_B = np.linalg.norm(B)
    return dot_product / (norm_A * norm_B)

def create_flat_embedding(text):
    logger.debug(f"create_flat_embedding >> Text :: {text}")
    embedding = llm_util.get_embedding(text)
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
        embedding = llm_util.get_embedding(context)
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

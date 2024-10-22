import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from util.llm_util import get_embedding_normalized


def deduplicate_articles(articles, threshold=0.85):
    # Get embeddings for each article
    embeddings = [get_embedding_normalized(article['summary']) for article in articles]
    
    # Calculate cosine similarity
    similarity_matrix = cosine_similarity(embeddings)

    deduplicated_indices = set()
    duplicates = []

    for i in range(len(articles)):
        if i not in deduplicated_indices:
            deduplicated_indices.add(i)
            for j in range(i + 1, len(articles)):
                similarity = similarity_matrix[i][j]
                if similarity > threshold:
                    print(f"Potential duplicate found: Article {i} and Article {j}")
                    print(f"Similarity: {similarity:.4f}")
                    print(f"Article {i}: {articles[i]['summary'][:100]}...")
                    print(f"Article {j}: {articles[j]['summary'][:100]}...")
                    print()
                    duplicates.append((i, j, similarity))
                    if articles[i]['date'] < articles[j]['date']:
                        deduplicated_indices.remove(i)
                        deduplicated_indices.add(j)
                        break
    
    deduplicated_articles = [articles[i] for i in deduplicated_indices]
    return deduplicated_articles, duplicates

# Sample articles
articles = [
    {
        "id": "1",
        "date": "2023-06-01",
        "summary": "Shein is intensifying its efforts to list on the London Stock Exchange, potentially valuing the online fashion retailer at £50 billion ($65 billion). The company has appointed Barclays and UBS as bookrunners for its initial public offering (IPO), which could occur as soon as early next year. This move follows Shein's unsuccessful attempt to list in the US, where the Securities and Exchange Commission rejected its request for a confidential preliminary prospectus."
    },
    {
        "id": "2",
        "date": "2023-06-02",
        "summary": "Shein, the fast-fashion giant, is advancing its plans for an initial public offering (IPO) in London by adding Barclays Plc and UBS Group AG as bookrunners. This follows its collaboration with major financial institutions like Goldman Sachs, JPMorgan, and Morgan Stanley. The IPO could value Shein at approximately £50 billion and may occur as early as next year, although details remain fluid."
    },
    {
        "id": "3",
        "date": "2023-06-03",
        "summary": "Apple unveils its latest iPhone model with revolutionary AI capabilities. The new device features advanced natural language processing and image recognition, setting a new standard for smartphone technology. Analysts predict this release will significantly boost Apple's market share in the coming year."
    },
    {
        "id": "4",
        "date": "2023-06-04",
        "summary": "Tesla announces breakthrough in battery technology, doubling the range of electric vehicles. The new batteries, set to enter production next year, promise to address range anxiety and accelerate the adoption of electric cars worldwide. Industry experts hail this as a game-changer for sustainable transportation."
    }
]

# Test the deduplication function with different thresholds
thresholds = [0.95, 0.90, 0.85, 0.80]
# thresholds = [0.75, 0.65, 0.55, 0.45]

for threshold in thresholds:
    print(f"\nTesting with threshold: {threshold}")
    deduplicated, duplicates = deduplicate_articles(articles, threshold)
    print(f"Number of articles after deduplication: {len(deduplicated)}")
    print(f"Number of duplicate pairs found: {len(duplicates)}")
    print("---")

# Print the final deduplicated articles
print("\nFinal deduplicated articles (using threshold 0.85):")
final_deduplicated, _ = deduplicate_articles(articles, 0.85)
for article in final_deduplicated:
    print(f"ID: {article['id']}, Date: {article['date']}")
    print(f"Summary: {article['summary'][:100]}...")
    print()

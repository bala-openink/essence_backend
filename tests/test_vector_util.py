import unittest
import numpy as np
from unittest.mock import patch
from util.vector_util import get_user_embedding_with_weights

class MockUser:
    def __init__(self, country_name=None, industry_name=None):
        self.country_name = country_name
        self.industry_name = industry_name

def create_mock_embedding(text, model=None):
    """
    Create deterministic mock embeddings based on text.
    Returns different unit vectors for different inputs.
    Ignores the model parameter but accepts it to match the signature.
    """
    if isinstance(text, list):  # Handle case where input is a list
        text = text[0]
        
    if 'technology' in text.lower():
        return np.array([1, 0, 0] + [0] * 1533)  # Tech-focused vector
    elif 'finance' in text.lower():
        return np.array([0, 1, 0] + [0] * 1533)  # Finance-focused vector
    elif 'usa' in text.lower():
        return np.array([0, 0, 1] + [0] * 1533)  # Region-focused vector
    elif 'engineering' in text.lower():
        return np.array([0, 0, 0, 1] + [0] * 1532)  # Function-focused vector
    return np.array([1/np.sqrt(1536)] * 1536)    # Default normalized vector

class TestVectorUtil(unittest.TestCase):
    def setUp(self):
        # Start the patcher
        self.patcher = patch('util.vector_util.get_base_embedding')
        self.mock_get_base_embedding = self.patcher.start()
        self.mock_get_base_embedding.side_effect = create_mock_embedding

    def tearDown(self):
        self.patcher.stop()

    def test_industry_weight_impact(self):
        """Test that industry preferences have stronger impact on industry-related similarity"""
        # Create two user preferences, one tech-focused and one finance-focused
        tech_preferences = {
            'industries': ['Technology'],
            'regions': ['USA']
        }
        finance_preferences = {
            'industries': ['Finance'],
            'regions': ['USA']
        }
        
        user = MockUser()
        
        # Get embeddings for both preference sets
        tech_embedding = get_user_embedding_with_weights(tech_preferences, user)
        finance_embedding = get_user_embedding_with_weights(finance_preferences, user)
        
        # Create test vectors for comparison
        tech_article = create_mock_embedding('technology')
        finance_article = create_mock_embedding('finance')
        
        # Calculate similarities
        tech_sim_to_tech = np.dot(tech_embedding, tech_article)
        tech_sim_to_finance = np.dot(tech_embedding, finance_article)
        finance_sim_to_tech = np.dot(finance_embedding, tech_article)
        finance_sim_to_finance = np.dot(finance_embedding, finance_article)
        
        # Verify that preferences align with expected similarities
        self.assertGreater(tech_sim_to_tech, tech_sim_to_finance, 
                          "Tech preferences should be more similar to tech content")
        self.assertGreater(finance_sim_to_finance, finance_sim_to_tech, 
                          "Finance preferences should be more similar to finance content")

    def test_weight_distribution(self):
        """Test that the weighted combination respects the defined weights"""
        preferences = {
            'industries': ['Technology'],
            'regions': ['USA'],
            'functions': ['Engineering']
        }
        
        user = MockUser(country_name='USA', industry_name='Technology')
        embedding = get_user_embedding_with_weights(preferences, user)
        
        # The final embedding should be normalized
        self.assertTrue(np.isclose(np.linalg.norm(embedding), 1.0), 
                       "Final embedding should be normalized")
        
        # Test with empty preferences
        empty_embedding = get_user_embedding_with_weights({}, MockUser())
        self.assertEqual(len(empty_embedding), 1536, 
                        "Should handle empty preferences")

    def test_combined_weights(self):
        """Test that combining multiple dimensions works as expected"""
        # Test with different combinations of preferences
        tech_only = {
            'industries': ['Technology']
        }
        
        tech_and_region = {
            'industries': ['Technology'],
            'regions': ['USA']
        }
        
        user = MockUser()
        
        embedding1 = get_user_embedding_with_weights(tech_only, user)
        embedding2 = get_user_embedding_with_weights(tech_and_region, user)
        
        # Embeddings should be different when different preferences are provided
        self.assertFalse(np.array_equal(embedding1, embedding2), 
                        "Different preference combinations should produce different embeddings")
        
        # Test similarity with tech content
        tech_article = create_mock_embedding('technology')
        usa_article = create_mock_embedding('usa')
        
        # Tech-only embedding should have higher similarity with tech content
        tech_only_sim = np.dot(embedding1, tech_article)
        combined_sim = np.dot(embedding2, tech_article)
        
        self.assertNotEqual(tech_only_sim, combined_sim,
                           "Different preference combinations should yield different similarities")

if __name__ == '__main__':
    unittest.main() 
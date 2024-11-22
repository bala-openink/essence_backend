import re

def test_clean_text(text):
    cleaned = re.sub(r'^(?:Emily|Harry|male|female)[:\s]*|[:\s]*(?:Emily|Harry|male|female)$', '', text, flags=re.IGNORECASE)
    return cleaned

# Test cases
test_inputs = [
    "Emily: Hello harry there",
    "HARRY: Hello there",
    "male Hello there",
    "Hello there - female",
    "Hello there Harry",
    "FEMALE: Hello harrythere male",  # Tests if it handles both start and end
    "emily   Hello there",       # Multiple spaces
    "Hello there    HARRY",      # Multiple spaces
    "Male:Hello there",          # No space after colon
    "Hello there:Female",        # Different separator
    "Just normal text",          # No names to remove
    "HarryPotter: Hello there",  # Should not match (part of another word)
    "Hello thereHarry",          # Should not match (part of another word)
]

print("Testing text cleaning:")
for test in test_inputs:
    cleaned = test_clean_text(test)
    print(f"Original: '{test}'")
    print(f"Cleaned:  '{cleaned}'")
    print("-" * 50)

duration_minutes = 10
language = "en"
region = "US"
narrative_prompt = "The conversation should be about the latest news in the world."

podcast_prompt = f"""
        Create a natural, engaging podcast conversation between the hosts, Harry and Emily using all the relevant articles provided. 

        Key requirements:
        Target duration: {duration_minutes} minutes (approximately {duration_minutes * 120} words)
        The conversation should be in {language} and reflect the cultural and linguistic style of the {region} region.
        {narrative_prompt}
        Return the output as an array of dialogue turns in JSON format like: [{{"speaker": "male", "text": "..."}}, {{"speaker": "female", "text": "..."}}]
        """
print(podcast_prompt)
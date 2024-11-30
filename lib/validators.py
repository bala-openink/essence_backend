import re
from fuzzywuzzy import process
import pycountry

def validate_email(email):
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def validate_country(country_input):
    # Common abbreviations mapping
    abbreviations = {
        'USA': 'US',
        'UK': 'GB',
        'UAE': 'AE',
        'ROK': 'KR',  # Republic of Korea
        'PRC': 'CN',  # People's Republic of China
        # Add more common abbreviations as needed
    }

    # Clean input
    country_input = country_input.strip().upper()

    # Check if it's a common abbreviation
    if country_input in abbreviations:
        country_input = abbreviations[country_input]

    # Create dictionaries for lookup
    countries = {country.alpha_2: country.name for country in pycountry.countries}
    countries_reverse = {country.name.upper(): country.alpha_2 for country in pycountry.countries}

    # If input is a valid 2-letter code, return immediately
    if len(country_input) == 2 and country_input in countries:
        return countries[country_input], country_input

    # If input is an exact match for a country name
    if country_input in countries_reverse:
        return country_input, countries_reverse[country_input]

    # Only do fuzzy matching if input is longer than 3 characters
    if len(country_input) > 3:
        # Get top matches instead of just one
        matches = process.extractBests(country_input, countries_reverse.keys(), score_cutoff=90, limit=2)
        
        # If we have exactly one high-confidence match, use it
        if len(matches) == 1 and matches[0][1] >= 90:
            match = matches[0][0]
            return match, countries_reverse[match]
        
        # If we have multiple close matches, it's ambiguous
        if len(matches) > 1 and matches[1][1] >= 85:
            raise ValueError("Ambiguous country input - matches multiple countries")

    raise ValueError("Invalid country input")

def validate_language(language_input):
    # Create a dictionary for language codes and names, and vice versa
    languages = {language.alpha_2: language.name for language in pycountry.languages if hasattr(language, 'alpha_2')}
    languages.update({language.name: language.alpha_2 for language in pycountry.languages if hasattr(language, 'alpha_2')})

    # Try to match the input with language codes or names
    if language_input.lower() in languages:
        return languages[language_input.lower()], language_input.lower()
    if language_input.title() in languages:
        return language_input.title(), languages[language_input.title()]

    # Fuzzy match if exact match not found
    match, score = process.extractOne(language_input, languages.keys())
    if score > 80:  # Adjust threshold as needed
        return languages[match], match

    raise ValueError("Invalid language input")

# Quick tests
# print(validate_language("tamil"))      # Returns ("Tamil", "ta")
# print(validate_language("tamizh"))       # Returns ("Tamil", "ta")
# print(validate_language("urdu"))   # Returns ("Tamil", "ta") via fuzzy matching
# print(validate_country("U"))        # Raises ValueError (too short for fuzzy matching)
# print(validate_country("XX"))       # Raises ValueError (invalid country code)
import re
import pycountry

def validate_email(email):
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def validate_country(country_code):
    return country_code.upper() in [country.alpha_2 for country in pycountry.countries]

def validate_language(language_code):
    return language_code.lower() in [language.alpha_2.lower() for language in pycountry.languages if hasattr(language, 'alpha_2')]
import os
from dotenv import load_dotenv, find_dotenv

# Load default environment variables from .env.default
load_dotenv(find_dotenv('.env.default'), override=False)
# Load overriding environment variables from .env
load_dotenv(find_dotenv('.env'), override=True)

class Config:
    LEMMY_SERVER = os.getenv('LEMMY_SERVER')
    LEMMY_USERNAME = os.getenv('LEMMY_USERNAME')
    LEMMY_FREE_USERNAME = os.getenv('LEMMY_FREE_USERNAME')
    LEMMY_PAYWALL_USERNAME = os.getenv('LEMMY_PAYWALL_USERNAME')
    LEMMY_PASSWORD = os.getenv('LEMMY_PASSWORD')
    LEMMY_COMMUNITY = os.getenv('LEMMY_COMMUNITY')
    REQUEST_DELAY = int(os.getenv('REQUEST_DELAY'))
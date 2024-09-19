import os
from dotenv import load_dotenv, find_dotenv

# Load default environment variables from .env.default
load_dotenv(find_dotenv('.env.default'), override=False)
# Load overriding environment variables from .env
load_dotenv(find_dotenv('.env'), override=True)

class Config:
    LEMMY_SERVER = os.getenv('LEMMY_SERVER')
    LEMMY_USERNAME = os.getenv('LEMMY_USERNAME')
    LEMMY_FREE_BOT = os.getenv('LEMMY_FREE_BOT')
    LEMMY_PAYWALL_BOT = os.getenv('LEMMY_PAYWALL_BOT')
    LEMMY_ADDITIONAL_MODS = os.getenv('LEMMY_ADDITIONAL_MODS')
    LEMMY_PASSWORD = os.getenv('LEMMY_PASSWORD')
    LEMMY_COMMUNITY = os.getenv('LEMMY_COMMUNITY')
    REQUEST_DELAY = int(os.getenv('REQUEST_DELAY'))
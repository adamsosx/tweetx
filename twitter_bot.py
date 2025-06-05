import tweepy
import requests
import json
from datetime import datetime, timezone # Dodano timezone dla UTC
import logging
import os 

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Logowanie do konsoli/outputu Akcji
)

api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

RADAR_API_URL = "https://radar.fun/api/tokens/most-called?timeframe=1h"

def get_top_tokens():
    """Pobiera dane z API radar.fun i zwraca top 3 tokeny"""
    try:
        response = requests.get(RADAR_API_URL, verify=False)
        response.raise_for_status()
        data = response.json()
        
        sorted_tokens = sorted(data, key=lambda x: x.get('calls1h', 0), reverse=True)
        
        top_3 = sorted_tokens[:3]
        return top_3
    except requests.exceptions.SSLError as e:
        logging.error(f"SSL Error fetching data from radar.fun API: {e}.")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Request Error fetching data from radar.fun API: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error from radar.fun API: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in get_top_tokens: {e}")
        return None

def format_tweet(top_3_tokens):
    """Format tweet with top 3 tokens - TWOJA ORYGINALNA WERSJA FORMATOWANIA"""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M") # Zmieniono na UTC
    tweet = f"Top 3 Most Called Tokens (1h)\n\n" 

    for i, token in enumerate(top_3_tokens, 1):
        calls = token.get('unique_channels', 0) 
        symbol = token.get('symbol', 'Unknown')
        address = token.get('address', 'No Address Provided') 
        
        # Linia 1: Numer porządkowy, symbol
        tweet += f"{i}. ${symbol}\n"
        
        # Linia 2: Adres (w nowej linii, z wcięciem)
        tweet += f"   {address}\n"
        
         # Linia 3: Liczba wywołań (w nowej linii, z wcięciem)
        tweet += f"   {calls} calls\n\n" 
          
    if top_3_tokens:
        tweet = tweet.rstrip('\n') + "\n" 
        
    tweet += "\n outlight.fun\n"
            
    return tweet

def main():
    logging.info("GitHub Action: Bot execution started.")
    
    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("CRITICAL: One or more Twitter API keys are missing from environment variables. Exiting.")
        return

    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        me = client.get_me()
        logging.info(f"Successfully authenticated on Twitter as @{me.data.username}")
    except tweepy.TweepyException as e:
        logging.error(f"Tweepy Error creating Twitter client or authenticating: {e}")
        return
    except Exception as e:
        logging.error(f"Unexpected error during Twitter client setup: {e}")
        return

    top_3 = get_top_tokens()
    if not top_3:
        logging.error("Failed to fetch top tokens or no tokens returned. Skipping tweet.")
        return

    tweet_text = format_tweet(top_3)
    logging.info(f"Prepared tweet ({len(tweet_text)} chars):")
    logging.info(tweet_text)

    if len(tweet_text) > 280:
        logging.warning(f"Generated tweet is too long ({len(tweet_text)} chars). Twitter will likely reject it.")
        

    try:
        response = client.create_tweet(text=tweet_text)
        tweet_id = response.data['id']
        logging.info(f"Tweet sent successfully! Tweet ID: {tweet_id}, Link: https://twitter.com/{me.data.username}/status/{tweet_id}")
    except tweepy.TweepyException as e:
        logging.error(f"Twitter API error sending tweet: {e}")
        # Jeśli błąd to 403 Forbidden, log zawierał "You are not permitted to perform this action."
        # To wskazuje na problem z uprawnieniami aplikacji na Twitter Developer Portal.
    except Exception as e:
        logging.error(f"Unexpected error sending tweet: {e}")
        
    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    if 'requests' in globals() and hasattr(requests, 'packages') and hasattr(requests.packages, 'urllib3'):
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("SSL verification is disabled for requests (verify=False). "
                            "This is not recommended for production environments.")
        except AttributeError:
            pass
    main()

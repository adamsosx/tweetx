import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
import functools
import random
from requests.exceptions import ConnectionError, Timeout, RequestException
from urllib3.exceptions import ProtocolError

# Dodane do obsługi uploadu grafiki
from tweepy import OAuth1UserHandler, API

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Logowanie do konsoli/outputu Akcji
)

# Dekorator do obsługi rate limit i błędów połączenia
def rate_limit_handler(max_retries=3, base_delay=60):
    """
    Dekorator do obsługi rate limit Twitter API i błędów połączenia.
    Automatycznie ponawia żądania z exponential backoff.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            delay = base_delay
            
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except tweepy.TooManyRequests as e:
                    if retries == max_retries:
                        logging.error(f"Rate limit exceeded after {max_retries} retries for {func.__name__}")
                        raise
                    
                    # Pobierz czas resetu z nagłówków
                    reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
                    current_time = int(time.time())
                    wait_time = max(reset_time - current_time + 10, delay)
                    
                    # Ogranicz maksymalny czas oczekiwania do 10 minut dla GitHub Actions
                    wait_time = min(wait_time, 600)
                    
                    # Dodaj losowe opóźnienie (jitter) aby uniknąć thundering herd
                    jitter = random.randint(0, min(30, int(wait_time * 0.1)))
                    wait_time += jitter
                    
                    logging.warning(f"Rate limit hit in {func.__name__}. Waiting {wait_time} seconds before retry {retries + 1}/{max_retries}")
                    wait_with_progress(wait_time, f"rate limit reset for {func.__name__}")
                    
                    retries += 1
                    delay *= 2  # Exponential backoff
                    
                except (ConnectionError, ProtocolError, Timeout, RequestException) as e:
                    if retries == max_retries:
                        logging.error(f"Network error after {max_retries} retries for {func.__name__}: {e}")
                        return None
                    
                    # Krótszy czas oczekiwania dla błędów połączenia
                    network_delay = min(delay, 30)
                    jitter = random.randint(1, 10)
                    wait_time = network_delay + jitter
                    
                    logging.warning(f"Network error in {func.__name__}: {e}. Waiting {wait_time} seconds before retry {retries + 1}/{max_retries}")
                    wait_with_progress(wait_time, f"network retry for {func.__name__}")
                    
                    retries += 1
                    delay = min(delay * 1.5, 60)  # Wolniejszy exponential backoff dla błędów sieciowych
                    
                except tweepy.TweepyException as e:
                    if retries == max_retries:
                        logging.error(f"Tweepy error after {max_retries} retries for {func.__name__}: {e}")
                        return None
                    
                    # Krótki czas oczekiwania dla błędów API
                    api_delay = min(delay // 2, 30) 
                    jitter = random.randint(1, 5)
                    wait_time = api_delay + jitter
                    
                    logging.warning(f"Tweepy error in {func.__name__}: {e}. Waiting {wait_time} seconds before retry {retries + 1}/{max_retries}")
                    wait_with_progress(wait_time, f"API retry for {func.__name__}")
                    
                    retries += 1
                    delay = min(delay * 1.5, 60)
                    
                except Exception as e:
                    # Nieoczekiwane wyjątki - loguj i zwróć None
                    logging.error(f"Unexpected error in {func.__name__}: {e}")
                    return None
            
            return None
        return wrapper
    return decorator

class RateLimitMonitor:
    """Klasa do monitorowania limitów rate limit Twitter API"""
    def __init__(self):
        self.limits = {}
        
    def update_from_response(self, endpoint, response):
        """Aktualizuje informacje o limitach na podstawie odpowiedzi API"""
        if hasattr(response, 'headers'):
            headers = response.headers
            self.limits[endpoint] = {
                'limit': int(headers.get('x-rate-limit-limit', 0)),
                'remaining': int(headers.get('x-rate-limit-remaining', 0)),
                'reset': int(headers.get('x-rate-limit-reset', 0))
            }
            
            # Ostrzeżenie gdy pozostało mało wywołań
            remaining = self.limits[endpoint]['remaining']
            if remaining < 5:
                reset_time = datetime.fromtimestamp(self.limits[endpoint]['reset'], tz=timezone.utc)
                logging.warning(f"Low rate limit for {endpoint}: {remaining} calls remaining. Reset at {reset_time}")
    
    def should_wait(self, endpoint, threshold=2):
        """Sprawdza czy powinniśmy poczekać przed następnym wywołaniem"""
        if endpoint in self.limits:
            if self.limits[endpoint]['remaining'] <= threshold:
                return True, self.limits[endpoint]['reset']
        return False, None

# Instancja monitora rate limit
rate_monitor = RateLimitMonitor()

def wait_with_progress(wait_time, action_name):
    """Czeka z pokazywaniem postępu co minutę"""
    if wait_time <= 60:
        time.sleep(wait_time)
        return
    
    logging.info(f"Starting {wait_time} second wait for {action_name}...")
    start_time = time.time()
    
    while True:
        elapsed = time.time() - start_time
        remaining = wait_time - elapsed
        
        if remaining <= 0:
            break
            
        if elapsed > 0 and int(elapsed) % 60 == 0:  # Log co minutę
            minutes_remaining = int(remaining // 60)
            seconds_remaining = int(remaining % 60)
            logging.info(f"Still waiting for {action_name}: {minutes_remaining}m {seconds_remaining}s remaining...")
        
        time.sleep(min(1, remaining))  # Śpi maksymalnie 1 sekundę
    
    logging.info(f"Wait completed for {action_name}")

def should_continue_waiting(wait_time, max_wait=900):
    """
    Sprawdza czy warto kontynuować oczekiwanie na rate limit.
    GitHub Actions ma ograniczenia czasowe, więc długie oczekiwanie może nie mieć sensu.
    """
    if wait_time > max_wait:
        logging.warning(f"Rate limit wait time ({wait_time}s) exceeds maximum ({max_wait}s). Consider skipping this execution.")
        return False
    return True

# Klucze API odczytywane ze zmiennych środowiskowych
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# URL API outlight.fun - (1h timeframe)
OUTLIGHT_API_URL = "https://outlight.fun/api/tokens/most-called?timeframe=1h"

def get_top_tokens():
    """Pobiera dane z API outlight.fun i zwraca top 5 tokenów, licząc tylko kanały z win_rate > 30%"""
    try:
        response = requests.get(OUTLIGHT_API_URL, verify=False, timeout=30)
        response.raise_for_status()
        data = response.json()

        tokens_with_filtered_calls = []
        for token in data:
            channel_calls = token.get('channel_calls', [])
            # Licz tylko kanały z win_rate > 30%
            calls_above_30 = [call for call in channel_calls if call.get('win_rate', 0) > 30]
            count_calls = len(calls_above_30)
            if count_calls > 0:
                token_copy = token.copy()
                token_copy['filtered_calls'] = count_calls
                tokens_with_filtered_calls.append(token_copy)

        # Sortuj po liczbie filtered_calls malejąco
        sorted_tokens = sorted(tokens_with_filtered_calls, key=lambda x: x.get('filtered_calls', 0), reverse=True)
        # Zwracamy Top 5
        top_5 = sorted_tokens[:5]
        return top_5
    except Exception as e:
        logging.error(f"Unexpected error in get_top_tokens: {e}")
        return None

def format_main_tweet(top_3_tokens):
    """Format tweet with top 3 tokens."""
    tweet = f"🚀Top 5 Most 📞 1h\n\n"
    medals = ['🥇', '🥈', '🥉']
    for i, token in enumerate(top_3_tokens, 0):
        calls = token.get('filtered_calls', 0)
        symbol = token.get('symbol', 'Unknown')
        address = token.get('address', 'No Address Provided')
        medal = medals[i]
        tweet += f"{medal} ${symbol}\n"
        tweet += f"{address}\n"
        tweet += f"📞 {calls}\n\n"
    tweet = tweet.rstrip('\n') + '\n'
    return tweet

def format_reply_tweet(continuation_tokens):
    """
    Formatuje drugiego tweeta (odpowiedź).
    Zawiera tokeny 4 i 5 (jeśli istnieją), a następnie link i hashtagi.
    """
    tweet = ""
    # Dodaj tokeny 4 i 5, jeśli istnieją
    if continuation_tokens:
        for i, token in enumerate(continuation_tokens, 4):
            calls = token.get('filtered_calls', 0)
            symbol = token.get('symbol', 'Unknown')
            address = token.get('address', 'No Address Provided')
            medal = f"{i}."
            tweet += f"{medal} ${symbol}\n"
            tweet += f"{address}\n"
            tweet += f"📞 {calls}\n\n"
    
    # Zawsze dodaj link i hashtagi na końcu
    tweet += "\ud83e\uddea Data from: \ud83d\udd17 https://outlight.fun/\n#SOL #Outlight #TokenCalls "
    return tweet.strip()

# Funkcje opakowujące z obsługą rate limit
@rate_limit_handler(max_retries=3)
def safe_get_me(client):
    """Bezpieczne pobieranie informacji o użytkowniku z obsługą rate limit"""
    return client.get_me()

@rate_limit_handler(max_retries=3)
def safe_create_tweet(client, **kwargs):
    """Bezpieczne tworzenie tweeta z obsługą rate limit"""
    return client.create_tweet(**kwargs)

@rate_limit_handler(max_retries=3, base_delay=30)
def safe_media_upload(api_v1, image_path):
    """Bezpieczne uploadowanie media z obsługą rate limit"""
    return api_v1.media_upload(image_path)

def main():
    logging.info("GitHub Action: Bot execution started.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("CRITICAL: One or more Twitter API keys are missing from environment variables. Exiting.")
        return

    try:
        # Klient v2
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=False  # Wyłączamy wbudowaną obsługę rate limit
        )
        me = safe_get_me(client)
        if me:
            logging.info(f"Successfully authenticated on Twitter as @{me.data.username}")
        else:
            logging.error("Failed to authenticate on Twitter after retries.")
            return

        # Klient v1.1 do uploadu grafiki
        auth_v1 = OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        api_v1 = API(auth_v1)
    except tweepy.TweepyException as e:
        logging.error(f"Tweepy Error creating Twitter client or authenticating: {e}")
        return
    except Exception as e:
        logging.error(f"Unexpected error during Twitter client setup: {e}")
        return

    top_tokens = get_top_tokens()
    if not top_tokens:
        logging.warning("Failed to fetch top tokens or no tokens returned. Skipping tweet.")
        return

    # Przygotowanie i wysłanie głównego tweeta (tokeny 1-3)
    main_tweet_text = format_main_tweet(top_tokens[:3])
    logging.info(f"Prepared main tweet ({len(main_tweet_text)} chars):")
    logging.info(main_tweet_text)

    if len(main_tweet_text) > 280:
        logging.warning(f"Generated main tweet is too long ({len(main_tweet_text)} chars).")

    # --- Dodanie grafiki do głównego tweeta ---
    image_path = os.path.join("images", "msgtwt.png")
    media_id = None
    if not os.path.isfile(image_path):
        logging.error(f"Image file not found: {image_path}. Sending tweet without image.")
    else:
        try:
            media = safe_media_upload(api_v1, image_path)
            if media:
                media_id = media.media_id
                logging.info(f"Image uploaded successfully. Media ID: {media_id}")
            else:
                logging.error("Failed to upload image after retries. Sending tweet without image.")
        except Exception as e:
            logging.error(f"Error uploading image: {e}. Sending tweet without image.")

    # Wysyłanie głównego tweeta
    response_main_tweet = safe_create_tweet(
        client,
        text=main_tweet_text,
        media_ids=[media_id] if media_id else None
    )
    
    if not response_main_tweet:
        logging.error("Failed to send main tweet after retries. Exiting.")
        return
        
    main_tweet_id = response_main_tweet.data['id']
    logging.info(f"Main tweet sent successfully! Tweet ID: {main_tweet_id}")

    # Czekaj przed wysłaniem odpowiedzi
    logging.info("Waiting 2 minutes before sending reply tweet...")
    wait_with_progress(120, "reply tweet delay")

    # Przygotowanie i wysłanie odpowiedzi (tokeny 4-5 + link)
    continuation_tokens = top_tokens[3:5]
    reply_tweet_text = format_reply_tweet(continuation_tokens)
    logging.info(f"Prepared reply tweet ({len(reply_tweet_text)} chars):")
    logging.info(reply_tweet_text)

    if len(reply_tweet_text) > 280:
        logging.warning(f"Generated reply tweet is too long ({len(reply_tweet_text)} chars).")

    # --- Dodanie grafiki do odpowiedzi ---
    reply_image_path = os.path.join("images", "msgtwtft.png")
    reply_media_id = None
    if not os.path.isfile(reply_image_path):
        logging.error(f"Reply image file not found: {reply_image_path}. Sending reply without image.")
    else:
        try:
            reply_media = safe_media_upload(api_v1, reply_image_path)
            if reply_media:
                reply_media_id = reply_media.media_id
                logging.info(f"Reply image uploaded successfully. Media ID: {reply_media_id}")
            else:
                logging.error("Failed to upload reply image after retries. Sending reply without image.")
        except Exception as e:
            logging.error(f"Error uploading reply image: {e}. Sending reply without image.")
    
    # Wyślij odpowiedź
    response_reply_tweet = safe_create_tweet(
        client,
        text=reply_tweet_text,
        in_reply_to_tweet_id=main_tweet_id,
        media_ids=[reply_media_id] if reply_media_id else None
    )
    
    if not response_reply_tweet:
        logging.error("Failed to send reply tweet after retries.")
        return
        
    reply_tweet_id = response_reply_tweet.data['id']
    logging.info(f"Reply tweet sent successfully! Tweet ID: {reply_tweet_id}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    if 'requests' in globals() and hasattr(requests, 'packages') and hasattr(requests.packages, 'urllib3'):
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("SSL verification is disabled for requests (verify=False). This is not recommended.")
        except AttributeError:
            logging.warning("Could not disable InsecureRequestWarning for requests.")
    main()

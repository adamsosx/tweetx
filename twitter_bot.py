import tweepy
import requests
import json
from datetime import datetime, timezone # Dodano timezone dla UTC
import logging
import os

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Logowanie do konsoli/outputu Akcji
)

# Klucze API odczytywane ze zmiennych środowiskowych
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# URL API radar.fun - z pierwszego kodu (1h timeframe)
RADAR_API_URL = "https://radar.fun/api/tokens/most-called?timeframe=1h"

def get_top_tokens():
    """Pobiera dane z API radar.fun i zwraca top 3 tokeny"""
    try:
        # W pierwszym kodzie było verify=False, zachowujemy to z ostrzeżeniem na końcu skryptu
        response = requests.get(RADAR_API_URL, verify=False)
        response.raise_for_status()  # Wywoła wyjątek dla kodów błędu HTTP
        data = response.json()

        # Sortujemy tokeny według liczby wywołań w ostatniej godzinie ('calls1h')
        # Zgodnie z RADAR_API_URL timeframe=1h
        sorted_tokens = sorted(data, key=lambda x: x.get('unique_channels', 0), reverse=True)

        # Bierzemy top 3 tokeny
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
    """Format tweet with top 3 tokens"""
    # Timestamp nie jest używany w tweecie, ale logi mają własne.
    # Używamy timeframe z RADAR_API_URL
    tweet = f"Top 3 Most Called Tokens (1h)\n\n"

    for i, token in enumerate(top_3_tokens, 1):
        # Używamy 'calls1h' zgodnie z sortowaniem w get_top_tokens i timeframe URL
        calls = token.get('calls1h', 0)
        symbol = token.get('symbol', 'Unknown')
        address = token.get('address', 'No Address Provided')

        # Linia 1: Numer porządkowy, symbol
        tweet += f"{i}. ${symbol}\n"
        # Linia 2: Adres (w nowej linii, z wcięciem)
        tweet += f"   {address}\n"
        # Linia 3: Liczba wywołań (w nowej linii, z wcięciem)
        tweet += f"   {calls} calls\n\n"

    # Usuwa ostatnie puste linie dodane przez pętlę
    tweet = tweet.rstrip('\n')

    # Dodajemy informację, że źródło/link będzie w odpowiedzi
    tweet += "\n\nSource 👇"

    return tweet

def format_link_tweet():
    """Format the link tweet (reply)"""
    return "🔗 https://outlight.fun/ #SOL #Outlight"

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
    if not top_3: # Obsługuje zarówno None (błąd API) jak i pustą listę (brak tokenów)
        logging.warning("Failed to fetch top tokens or no tokens returned. Skipping tweet.")
        return

    tweet_text = format_tweet(top_3)
    logging.info(f"Prepared main tweet ({len(tweet_text)} chars):")
    logging.info(tweet_text)

    if len(tweet_text) > 280:
        logging.warning(f"Generated main tweet is too long ({len(tweet_text)} chars). Twitter will likely reject it.")
        # Można dodać return, jeśli nie chcemy próbować wysyłać za długiego tweeta
        # return

    try:
        # Wysyłanie głównego tweeta
        response_main_tweet = client.create_tweet(text=tweet_text)
        main_tweet_id = response_main_tweet.data['id']
        logging.info(f"Main tweet sent successfully! Tweet ID: {main_tweet_id}, Link: https://twitter.com/{me.data.username}/status/{main_tweet_id}")

        # Przygotowanie i wysłanie tweeta z linkiem jako odpowiedzi
        link_tweet_text = format_link_tweet()
        logging.info(f"Prepared reply tweet ({len(link_tweet_text)} chars):")
        logging.info(link_tweet_text)

        if len(link_tweet_text) > 280:
            logging.warning(f"Generated reply tweet is too long ({len(link_tweet_text)} chars). Twitter will likely reject it.")
            # Można zdecydować, czy mimo to próbować wysłać, czy pominąć odpowiedź
            # return lub continue w pętli (ale tu nie ma pętli)

        response_reply_tweet = client.create_tweet(
            text=link_tweet_text,
            in_reply_to_tweet_id=main_tweet_id
        )
        reply_tweet_id = response_reply_tweet.data['id']
        logging.info(f"Reply tweet sent successfully! Tweet ID: {reply_tweet_id}, Link: https://twitter.com/{me.data.username}/status/{reply_tweet_id}")

    except tweepy.TweepyException as e:
        logging.error(f"Twitter API error sending tweet: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending tweet: {e}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    # Ostrzeżenie o wyłączeniu weryfikacji SSL, jeśli używane jest `verify=False` w `requests.get`
    if 'requests' in globals() and hasattr(requests, 'packages') and hasattr(requests.packages, 'urllib3'):
        try:
            # Wyłączenie ostrzeżeń InsecureRequestWarning, ponieważ verify=False jest używane celowo (choć niezalecane)
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("SSL verification is disabled for requests (verify=False). "
                            "This is not recommended for production environments but used here as in the original script.")
        except AttributeError:
            # Na wypadek gdyby struktura requests.packages.urllib3 się zmieniła
            logging.warning("Could not disable InsecureRequestWarning for requests.")
            pass
    main()

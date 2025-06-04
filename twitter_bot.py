import tweepy
import requests
import json
from datetime import datetime, timezone # Dodano timezone dla UTC
# import time # Już niepotrzebny dla logiki działania na GitHub Actions
import logging
import os # Potrzebny do odczytu zmiennych środowiskowych

# Konfiguracja logowania - logowanie do standardowego wyjścia dla GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Logowanie do konsoli/outputu Akcji
)

# Odczytaj dane API ze zmiennych środowiskowych (GitHub Secrets)
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# Endpoint radar.fun
RADAR_API_URL = "https://radar.fun/api/tokens/most-called?timeframe=1h"

def get_top_tokens():
    """Pobiera dane z API radar.fun i zwraca top 3 tokeny"""
    try:
        # UWAGA: verify=False jest niezalecane w produkcji. Rozważ rozwiązanie problemu z SSL.
        response = requests.get(RADAR_API_URL, verify=False)
        response.raise_for_status()
        data = response.json()
        
        # Sortujemy tokeny według 'unique_channels', ponieważ to wyświetlamy jako 'calls'
        sorted_tokens = sorted(data, key=lambda x: x.get('unique_channels', 0), reverse=True)
        
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
    # Używamy UTC dla spójności, niezależnie od miejsca uruchomienia skryptu
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    
    tweet = f"📢 Top 3 Most Called Tokens (Radar.fun 1h) - {timestamp} UTC\n\n" # Dodano emoji i źródło
    
    if not top_3_tokens:
        tweet += "No data available for top called tokens at the moment.\n"
        tweet += "\n#SOL #RadarFun"
        return tweet

    for i, token in enumerate(top_3_tokens, 1):
        calls = token.get('unique_channels', 0) # Metryka dla "calls"
        name = token.get('name', 'Unknown Name') # Dodajmy nazwę dla pełniejszej informacji
        symbol = token.get('symbol', 'N/A')
        address = token.get('address', 'No Address Provided') 

        tweet += f"{i}. ${symbol} ({name})\n" # Dodano nazwę tokena
        tweet += f"   CA: {address}\n"
        tweet += f"   Calls: {calls}\n\n" # Zmieniono "calls calls" na "Calls: {calls}"
          
    # Usunięcie ostatniego podwójnego \n jeśli lista tokenów nie była pusta
    if top_3_tokens:
        tweet = tweet.rstrip('\n') + "\n"

    tweet += "\n#SOL #Crypto #DeFi #TopTokens #Altcoins #RadarFun" # Dodano więcej hashtagów
    
    # Proste skracanie tweeta, jeśli jest za długi (Twitter ma limit 280 znaków)
    if len(tweet) > 280:
        logging.warning(f"Tweet is too long ({len(tweet)} chars), will be truncated to 280.")
        # Obcięcie i dodanie "..." na końcu
        tweet = tweet[:277] + "..."
            
    return tweet

def main():
    """Główna funkcja bota, przeznaczona do jednorazowego uruchomienia."""
    logging.info("GitHub Action: Bot execution started.")
    
    # Sprawdzenie, czy klucze API zostały załadowane
    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("CRITICAL: One or more Twitter API keys are missing from environment variables. Exiting.")
        return # Zakończ, jeśli brakuje kluczy

    # Utwórz klienta API v2
    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        # Weryfikacja, czy autentykacja się powiodła (opcjonalne, ale dobre)
        me = client.get_me()
        logging.info(f"Successfully authenticated on Twitter as @{me.data.username}")
    except tweepy.TweepyException as e:
        logging.error(f"Tweepy Error creating Twitter client or authenticating: {e}")
        return
    except Exception as e: # Inne błędy
        logging.error(f"Unexpected error during Twitter client setup: {e}")
        return

    # Pobierz top 3 tokeny
    top_3 = get_top_tokens()
    if not top_3:
        logging.error("Failed to fetch top tokens or no tokens returned. Skipping tweet.")
        return # Zakończ, jeśli nie ma danych

    # Utwórz tweet
    tweet_text = format_tweet(top_3)
    logging.info(f"Prepared tweet ({len(tweet_text)} chars):")
    logging.info(tweet_text)

    # Wyślij tweet
    try:
        response = client.create_tweet(text=tweet_text)
        tweet_id = response.data['id'] # Zakładając, że odpowiedź zawiera 'data' i 'id'
        logging.info(f"Tweet sent successfully! Tweet ID: {tweet_id}, Link: https://twitter.com/{me.data.username}/status/{tweet_id}")
    except tweepy.TweepyException as e:
        logging.error(f"Twitter API error sending tweet: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending tweet: {e}")
        
    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    # Dodatkowe ostrzeżenie dotyczące verify=False, jeśli jest używane w requests
    # To ostrzeżenie pojawi się w logach GitHub Actions
    if 'requests' in globals() and hasattr(requests, 'packages') and hasattr(requests.packages, 'urllib3'):
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("SSL verification is disabled for requests (verify=False). "
                            "This is not recommended for production environments.")
        except AttributeError: # Na wypadek gdyby struktura urllib3 się zmieniła
            pass
    main()

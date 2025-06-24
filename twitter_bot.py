import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
from tweepy import OAuth1UserHandler, API

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# Klucze API
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

OUTLIGHT_API_URL = "https://outlight.fun/api/tokens/most-called?timeframe=1h"

def safe_tweet_with_retry(client, text, media_ids=None, in_reply_to_tweet_id=None, max_retries=3):
    """
    Bezpieczne wysyłanie tweeta z obsługą rate limitów i retry
    """
    for attempt in range(max_retries):
        try:
            response = client.create_tweet(
                text=text,
                media_ids=media_ids,
                in_reply_to_tweet_id=in_reply_to_tweet_id
            )
            logging.info(f"Tweet wysłany pomyślnie! ID: {response.data['id']}")
            return response
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 300)  # Min 5 min buffer
            
            logging.warning(f"Rate limit exceeded. Próba {attempt + 1}/{max_retries}")
            logging.warning(f"Oczekiwanie {wait_time} sekund przed ponowną próbą")
            
            if attempt < max_retries - 1:  # Nie czekaj przy ostatniej próbie
                time.sleep(wait_time)
            else:
                logging.error("Przekroczono maksymalną liczbę prób. Tweet nie został wysłany.")
                raise e
                
        except tweepy.Forbidden as e:
            logging.error(f"Błąd autoryzacji: {e}")
            raise e
            
        except tweepy.BadRequest as e:
            logging.error(f"Błędne żądanie (może za długi tweet?): {e}")
            raise e
            
        except Exception as e:
            logging.error(f"Nieoczekiwany błąd przy próbie {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(30)  # Krótka pauza przed retry
    
    return None

def safe_media_upload(api_v1, image_path, max_retries=3):
    """
    Bezpieczny upload mediów z obsługą rate limitów
    """
    if not os.path.isfile(image_path):
        logging.error(f"Plik obrazu nie znaleziony: {image_path}")
        return None
    
    for attempt in range(max_retries):
        try:
            media = api_v1.media_upload(image_path)
            logging.info(f"Obraz przesłany pomyślnie. Media ID: {media.media_id}")
            return media.media_id
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 180)
            
            logging.warning(f"Rate limit dla upload mediów. Próba {attempt + 1}/{max_retries}")
            logging.warning(f"Oczekiwanie {wait_time} sekund")
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logging.error("Nie udało się przesłać obrazu po wszystkich próbach")
                return None
                
        except Exception as e:
            logging.error(f"Błąd uploadu obrazu przy próbie {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(30)
    
    return None

def get_top_tokens():
    """Pobiera dane z API outlight.fun"""
    try:
        response = requests.get(OUTLIGHT_API_URL, verify=False)
        response.raise_for_status()
        data = response.json()

        tokens_with_filtered_calls = []
        for token in data:
            channel_calls = token.get('channel_calls', [])
            calls_above_30 = [call for call in channel_calls if call.get('win_rate', 0) > 30]
            count_calls = len(calls_above_30)
            if count_calls > 0:
                token_copy = token.copy()
                token_copy['filtered_calls'] = count_calls
                tokens_with_filtered_calls.append(token_copy)

        sorted_tokens = sorted(tokens_with_filtered_calls, key=lambda x: x.get('filtered_calls', 0), reverse=True)
        top_3 = sorted_tokens[:3]
        return top_3
    except Exception as e:
        logging.error(f"Błąd pobierania danych z API: {e}")
        return None

def format_tweet(top_3_tokens):
    """Formatowanie głównego tweeta"""
    tweet = f"🚀Top 3 Most 📞 1h\n\n"
    medals = ['🥇', '🥈', '🥉']
    for i, token in enumerate(top_3_tokens, 0):
        calls = token.get('filtered_calls', 0)
        symbol = token.get('symbol', 'Unknown')
        address = token.get('address', 'No Address Provided')
        medal = medals[i] if i < len(medals) else f"{i+1}."
        tweet += f"{medal} ${symbol}\n"
        tweet += f"{address}\n"
        tweet += f"📞 {calls}\n\n"
    tweet = tweet.rstrip('\n') + '\n\n'
    return tweet

def format_link_tweet():
    """Formatowanie tweeta z linkiem"""
    return "🧪 Data from: 🔗 https://outlight.fun/\n#SOL #Outlight #TokenCalls "

def main():
    logging.info("GitHub Action: Uruchomienie bota.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("Brak wymaganych kluczy API. Zakończenie.")
        return

    try:
        # Klienty Twitter API
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        me = client.get_me()
        logging.info(f"Autoryzacja pomyślna: @{me.data.username}")

        auth_v1 = OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        api_v1 = API(auth_v1)
        
    except Exception as e:
        logging.error(f"Błąd konfiguracji klientów Twitter: {e}")
        return

    # Pobieranie danych
    top_3 = get_top_tokens()
    if not top_3:
        logging.warning("Brak danych tokenów. Pomijanie tweeta.")
        return

    # Przygotowanie tekstów tweetów
    tweet_text = format_tweet(top_3)
    link_tweet_text = format_link_tweet()
    
    # Walidacja długości PRZED jakimikolwiek uploadami
    if len(tweet_text) > 280:
        logging.error(f"Główny tweet za długi ({len(tweet_text)} znaków). ANULOWANIE.")
        return
    
    if len(link_tweet_text) > 280:
        logging.error(f"Tweet odpowiedzi za długi ({len(link_tweet_text)} znaków). ANULOWANIE.")
        return

    try:
        # KROK 1: Upload WSZYSTKICH grafik na początku
        logging.info("=== KROK 1: Przesyłanie wszystkich grafik ===")
        
        main_image_path = os.path.join("images", "msgtwt.png")
        reply_image_path = os.path.join("images", "msgtwtft.png")
        
        # Upload pierwszej grafiki
        logging.info("Przesyłanie grafiki głównego tweeta...")
        main_media_id = safe_media_upload(api_v1, main_image_path)
        
        if not main_media_id:
            logging.error("❌ KRYTYCZNY BŁĄD: Nie udało się przesłać głównej grafiki.")
            logging.error("ANULOWANIE całego procesu - bez grafik nie wysyłamy tweetów.")
            return
        
        # Upload drugiej grafiki
        logging.info("Przesyłanie grafiki tweeta odpowiedzi...")
        reply_media_id = safe_media_upload(api_v1, reply_image_path)
        
        if not reply_media_id:
            logging.error("❌ KRYTYCZNY BŁĄD: Nie udało się przesłać grafiki odpowiedzi.")
            logging.error("ANULOWANIE całego procesu - bez grafik nie wysyłamy tweetów.")
            return
            
        logging.info("✅ SUKCES: Wszystkie grafiki przesłane pomyślnie!")
        logging.info(f"   - Główna grafika: Media ID {main_media_id}")
        logging.info(f"   - Grafika odpowiedzi: Media ID {reply_media_id}")
        
        # KROK 2: Wysłanie głównego tweeta (już z gwarancją grafiki)
        logging.info("=== KROK 2: Wysyłanie głównego tweeta z grafiką ===")
        main_tweet_response = safe_tweet_with_retry(
            client, 
            tweet_text, 
            media_ids=[main_media_id]
        )
        
        if not main_tweet_response:
            logging.error("❌ KRYTYCZNY BŁĄD: Nie udało się wysłać głównego tweeta!")
            logging.error("ANULOWANIE: Nie będzie wysyłana odpowiedź, bo główny tweet się nie udał.")
            return
            
        main_tweet_id = main_tweet_response.data['id']
        logging.info(f"✅ Główny tweet wysłany z grafiką! ID: {main_tweet_id}")
        
        # KROK 3: Bezpieczne oczekiwanie przed odpowiedzią
        logging.info("=== KROK 3: Oczekiwanie przed odpowiedzią ===")
        logging.info("Oczekiwanie 180 sekund przed wysłaniem odpowiedzi...")
        time.sleep(180)
        
        # KROK 4: Wysłanie odpowiedzi (tylko jeśli główny tweet się udał)
        logging.info("=== KROK 4: Wysyłanie tweeta odpowiedzi z grafiką ===")
        logging.info("Główny tweet został wysłany pomyślnie - kontynuowanie z odpowiedzią...")
        
        reply_response = safe_tweet_with_retry(
            client,
            link_tweet_text,
            media_ids=[reply_media_id],
            in_reply_to_tweet_id=main_tweet_id
        )
        
        if reply_response:
            logging.info(f"✅ Odpowiedź wysłana z grafiką! ID: {reply_response.data['id']}")
            logging.info("🎉 PEŁNY SUKCES: Oba tweety wysłane z grafikami!")
            logging.info(f"   🔗 Główny tweet: https://x.com/user/status/{main_tweet_id}")
            logging.info(f"   🔗 Odpowiedź: https://x.com/user/status/{reply_response.data['id']}")
        else:
            logging.error("❌ Nie udało się wysłać odpowiedzi mimo pomyślnego uploadu grafiki")
            logging.error(f"Główny tweet został jednak wysłany: https://x.com/user/status/{main_tweet_id}")

    except Exception as e:
        logging.error(f"Nieoczekiwany błąd podczas procesu: {e}")

    logging.info("GitHub Action: Zakończenie wykonania bota.")

if __name__ == "__main__":
    # Wyłączenie ostrzeżeń SSL
    if 'requests' in globals():
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("Weryfikacja SSL wyłączona dla requests")
        except AttributeError:
            pass
    
    main()

import tweepy
import time

import requests

import json

from datetime import datetime, timezone # Dodano timezone dla UTC

import logging

import os



# Dodane do obsługi uploadu grafiki

from tweepy import OAuth1UserHandler, API



# Ładowanie konfiguracji

def load_config(config_path="config.json"):

    """Ładuje konfigurację z pliku JSON"""

    try:

        with open(config_path, 'r', encoding='utf-8') as f:

            return json.load(f)

    except FileNotFoundError:

        logging.error(f"Plik konfiguracyjny {config_path} nie został znaleziony. Używam wartości domyślnych.")

        # Konfiguracja domyślna jako fallback

        return {

            "api": {"outlight_base_url": "https://outlight.fun/api/tokens/most-called", "timeframe": "1h", "verify_ssl": False},

            "token_filtering": {"min_win_rate": 30, "top_tokens_count": 3},

            "timing": {"reply_delay_seconds": 120},

            "images": {"main_tweet_image": "images/msgtwt.png", "reply_tweet_image": "images/msgtwtft.png"},

            "logging": {"level": "INFO", "format": "%(asctime)s - %(levelname)s - %(message)s"}

        }

    except json.JSONDecodeError as e:

        logging.error(f"Błąd parsowania konfiguracji: {e}. Używam wartości domyślnych.")

        return load_config.__defaults__[0] if hasattr(load_config, '__defaults__') else {}



# Ładowanie konfiguracji globalnej

config = load_config()



def retry_api_call(func, *args, **kwargs):

    """

    Wrapper do retry wywołań API Twitter z konfigurowalną logiką ponownych prób

    """

    retry_config = config.get('twitter', {}).get('retry', {})

    max_attempts = retry_config.get('max_attempts', 3)

    base_delay = retry_config.get('base_delay', 5)

    max_delay = retry_config.get('max_delay', 300)

    backoff_multiplier = retry_config.get('backoff_multiplier', 2)

    retryable_status_codes = retry_config.get('retryable_status_codes', [429, 500, 502, 503, 504])

    retryable_exceptions = retry_config.get('retryable_exceptions', ['ConnectionError', 'Timeout', 'TooManyRequests'])

    

    for attempt in range(max_attempts):

        try:

            return func(*args, **kwargs)

            

        except tweepy.TooManyRequests as e:

            if 'TooManyRequests' not in retryable_exceptions:

                raise

            

            # Specjalna obsługa rate limiting - używamy Twitter rate limit headers

            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))

            current_time = int(time.time())

            wait_time = max(reset_time - current_time + 10, base_delay)

            wait_time = min(wait_time, max_delay)

            

            if attempt < max_attempts - 1:

                logging.warning(f"Rate limit exceeded (attempt {attempt + 1}/{max_attempts}). "

                              f"Waiting {wait_time} seconds before retry...")

                time.sleep(wait_time)

            else:

                logging.error(f"Rate limit exceeded after {max_attempts} attempts. Giving up.")

                raise

                

        except tweepy.TweepyException as e:

            # Sprawdź czy to błąd, który można ponowić

            status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None

            exception_name = type(e).__name__

            

            is_retryable = (

                status_code in retryable_status_codes or

                exception_name in retryable_exceptions or

                'ConnectionError' in retryable_exceptions and 'connection' in str(e).lower() or

                'Timeout' in retryable_exceptions and 'timeout' in str(e).lower()

            )

            

            if not is_retryable or attempt >= max_attempts - 1:

                logging.error(f"Twitter API error (attempt {attempt + 1}/{max_attempts}): {e}")

                raise

            

            # Oblicz czas oczekiwania z exponential backoff

            delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)

            logging.warning(f"Twitter API error (attempt {attempt + 1}/{max_attempts}): {e}. "

                          f"Retrying in {delay} seconds...")

            time.sleep(delay)

            

        except Exception as e:

            # Dla innych błędów sprawdź czy są w liście retryable

            exception_name = type(e).__name__

            

            if exception_name not in retryable_exceptions or attempt >= max_attempts - 1:

                logging.error(f"Unexpected error (attempt {attempt + 1}/{max_attempts}): {e}")

                raise

            

            delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)

            logging.warning(f"Unexpected error (attempt {attempt + 1}/{max_attempts}): {e}. "

                          f"Retrying in {delay} seconds...")

            time.sleep(delay)



# Konfiguracja logowania

log_level = getattr(logging, config.get('logging', {}).get('level', 'INFO').upper())

log_format = config.get('logging', {}).get('format', '%(asctime)s - %(levelname)s - %(message)s')

logging.basicConfig(

    level=log_level,

    format=log_format,

    handlers=[logging.StreamHandler()] # Logowanie do konsoli/outputu Akcji

)

# Klucze API odczytywane ze zmiennych środowiskowych

api_key = os.getenv("TWITTER_API_KEY")

api_secret = os.getenv("TWITTER_API_SECRET")

access_token = os.getenv("TWITTER_ACCESS_TOKEN")

access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")



def retry_requests_call(func, *args, **kwargs):

    """Wrapper do retry dla wywołań requests API"""

    retry_attempts = config.get('api', {}).get('retry_attempts', 3)

    base_delay = 2

    

    for attempt in range(retry_attempts):

        try:

            return func(*args, **kwargs)

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, 

                requests.exceptions.HTTPError) as e:

            if attempt >= retry_attempts - 1:

                logging.error(f"API request failed after {retry_attempts} attempts: {e}")

                raise

            

            delay = base_delay * (2 ** attempt)

            logging.warning(f"API request failed (attempt {attempt + 1}/{retry_attempts}): {e}. "

                          f"Retrying in {delay} seconds...")

            time.sleep(delay)



def get_top_tokens():

    """Pobiera dane z API outlight.fun i zwraca top tokeny, licząc tylko kanały z win_rate > min_win_rate"""

    try:

        # Budowanie URL z parametrów konfiguracji

        base_url = config.get('api', {}).get('outlight_base_url', 'https://outlight.fun/api/tokens/most-called')

        timeframe = config.get('api', {}).get('timeframe', '1h')

        url = f"{base_url}?timeframe={timeframe}"

        

        verify_ssl = config.get('api', {}).get('verify_ssl', False)

        timeout = config.get('api', {}).get('request_timeout', 30)

        

        response = retry_requests_call(requests.get, url, verify=verify_ssl, timeout=timeout)

        response.raise_for_status()

        data = response.json()



        # Pobieranie parametrów filtrowania z konfiguracji

        min_win_rate = config.get('token_filtering', {}).get('min_win_rate', 30)

        top_count = config.get('token_filtering', {}).get('top_tokens_count', 3)



        tokens_with_filtered_calls = []

        for token in data:

            channel_calls = token.get('channel_calls', [])

            # Licz tylko kanały z win_rate > min_win_rate

            calls_above_threshold = [call for call in channel_calls if call.get('win_rate', 0) > min_win_rate]

            count_calls = len(calls_above_threshold)

            if count_calls > 0:

                token_copy = token.copy()

                token_copy['filtered_calls'] = count_calls

                tokens_with_filtered_calls.append(token_copy)



        # Sortuj po liczbie filtered_calls malejąco

        sorted_tokens = sorted(tokens_with_filtered_calls, key=lambda x: x.get('filtered_calls', 0), reverse=True)

        top_tokens = sorted_tokens[:top_count]

        return top_tokens

    except Exception as e:

        logging.error(f"Unexpected error in get_top_tokens: {e}")

        return None



def format_main_tweet(top_tokens):

    """Format main tweet with first 3 tokens using configurable templates"""

    # Pobieranie konfiguracji

    first_tweet_count = config.get('token_filtering', {}).get('first_tweet_count', 3)

    main_template = config.get('tweet_templates', {}).get('main_tweet', {})

    timeframe = config.get('api', {}).get('timeframe', '1h')

    total_count = config.get('token_filtering', {}).get('top_tokens_count', 5)

    

    # Używamy tylko pierwszych tokenów

    tokens_to_show = top_tokens[:first_tweet_count]

    

    header = main_template.get('header', '🚀Top {count} Most 📞 {timeframe}\n\n').format(

        count=total_count, timeframe=timeframe

    )

    medals = main_template.get('medals', ['🥇', '🥈', '🥉'])

    token_format = main_template.get('token_format', '{medal} ${symbol}\n{address}\n📞 {calls}\n\n')

    footer = main_template.get('footer', '')

    

    tweet = header

    for i, token in enumerate(tokens_to_show, 0):

        calls = token.get('filtered_calls', 0)

        symbol = token.get('symbol', 'Unknown')

        address = token.get('address', 'No Address Provided')

        medal = medals[i] if i < len(medals) else f"{i+1}."

        

        tweet += token_format.format(

            medal=medal,

            symbol=symbol,

            address=address,

            calls=calls

        )

    

    tweet = tweet.rstrip('\n') + footer

    return tweet



def format_tokens_reply_tweet(top_tokens):

    """Format reply tweet with remaining tokens (4-5) using configurable templates"""

    # Pobieranie konfiguracji

    first_tweet_count = config.get('token_filtering', {}).get('first_tweet_count', 3)

    total_count = config.get('token_filtering', {}).get('top_tokens_count', 5)

    reply_template = config.get('tweet_templates', {}).get('tokens_reply_tweet', {})

    

    # Używamy tokenów od indeksu first_tweet_count

    remaining_tokens = top_tokens[first_tweet_count:]

    

    if not remaining_tokens:

        return None

    

    header_template = reply_template.get('header', '')

    if header_template:

        header = header_template.format(total_count=total_count)

    else:

        header = ""

    medals = reply_template.get('medals', ['4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟'])

    token_format = reply_template.get('token_format', '{medal} ${symbol}\n{address}\n📞 {calls}\n\n')

    footer = reply_template.get('footer', '')

    

    tweet = header

    for i, token in enumerate(remaining_tokens, 0):

        calls = token.get('filtered_calls', 0)

        symbol = token.get('symbol', 'Unknown')

        address = token.get('address', 'No Address Provided')

        medal = medals[i] if i < len(medals) else f"{first_tweet_count + i + 1}."

        

        tweet += token_format.format(

            medal=medal,

            symbol=symbol,

            address=address,

            calls=calls

        )

    

    tweet = tweet.rstrip('\n') + footer

    return tweet







def main():

    logging.info("GitHub Action: Bot execution started.")



    if not all([api_key, api_secret, access_token, access_token_secret]):

        logging.error("CRITICAL: One or more Twitter API keys are missing from environment variables. Exiting.")

        return



    try:

        # Klient v2 do tweetów tekstowych i odpowiedzi

        client = tweepy.Client(

            consumer_key=api_key,

            consumer_secret=api_secret,

            access_token=access_token,

            access_token_secret=access_token_secret

        )

        me = client.get_me()

        logging.info(f"Successfully authenticated on Twitter as @{me.data.username}")



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

    if not top_tokens: # Obsługuje zarówno None (błąd API) jak i pustą listę (brak tokenów)

        logging.warning("Failed to fetch top tokens or no tokens returned. Skipping tweet.")

        return



    # Formatowanie głównego tweeta (top 3)

    main_tweet_text = format_main_tweet(top_tokens)

    logging.info(f"Prepared main tweet ({len(main_tweet_text)} chars):")

    logging.info(main_tweet_text)

    

    # Formatowanie tweeta z pozostałymi tokenami (4-5)

    tokens_reply_text = format_tokens_reply_tweet(top_tokens)

    if tokens_reply_text:

        logging.info(f"Prepared tokens reply tweet ({len(tokens_reply_text)} chars):")

        logging.info(tokens_reply_text)



    # Walidacja długości tweetów

    max_length = config.get('twitter', {}).get('max_tweet_length', 280)

    warn_on_long = config.get('twitter', {}).get('warn_on_long_tweet', True)

    

    if warn_on_long and len(main_tweet_text) > max_length:

        logging.warning(f"Generated main tweet is too long ({len(main_tweet_text)} chars). Twitter will likely reject it.")

    

    if tokens_reply_text and warn_on_long and len(tokens_reply_text) > max_length:

        logging.warning(f"Generated tokens reply tweet is too long ({len(tokens_reply_text)} chars). Twitter will likely reject it.")



    try:

        # --- Dodanie grafiki do głównego tweeta ---

        image_path = os.path.join("images", "msgtwt.png")

        if not os.path.isfile(image_path):

            logging.error(f"Image file not found: {image_path}. Sending tweet without image.")

            media_id = None

        else:

            try:

                media = retry_api_call(api_v1.media_upload, image_path)

                media_id = media.media_id

                logging.info(f"Image uploaded successfully. Media ID: {media_id}")

            except Exception as e:

                logging.error(f"Error uploading image: {e}. Sending tweet without image.")

                media_id = None



        # Wysyłanie głównego tweeta z grafiką (jeśli się udało) - z retry

        if media_id:

            response_main_tweet = retry_api_call(

                client.create_tweet, 

                text=main_tweet_text, 

                media_ids=[media_id]

            )

        else:

            response_main_tweet = retry_api_call(

                client.create_tweet, 

                text=main_tweet_text

            )

        main_tweet_id = response_main_tweet.data['id']

        logging.info(f"Main tweet sent successfully! Tweet ID: {main_tweet_id}")



        # Wysyłanie tweeta z pozostałymi tokenami (jeśli istnieją)

        tokens_reply_id = None

        if tokens_reply_text:

            # Wait before sending tokens reply

            tokens_delay = config.get('timing', {}).get('tokens_reply_delay_seconds', 120)

            logging.info(f"Waiting {tokens_delay} seconds before sending tokens reply...")

            time.sleep(tokens_delay)

            

            # Upload image for tokens reply

            tokens_image_path = config.get('images', {}).get('tokens_reply_image', 'images/msgtwt.png')

            tokens_media_id = None

            

            if not os.path.isfile(tokens_image_path):

                logging.error(f"Tokens reply image file not found: {tokens_image_path}. Sending reply without image.")

            else:

                try:

                    tokens_media = retry_api_call(api_v1.media_upload, tokens_image_path)

                    tokens_media_id = tokens_media.media_id

                    logging.info(f"Tokens reply image uploaded successfully. Media ID: {tokens_media_id}")

                except Exception as e:

                    logging.error(f"Error uploading tokens reply image: {e}. Sending reply without image.")

            

            # Send tokens reply tweet

            if tokens_media_id:

                response_tokens_reply = retry_api_call(

                    client.create_tweet,

                    text=tokens_reply_text,

                    in_reply_to_tweet_id=main_tweet_id,

                    media_ids=[tokens_media_id]

                )

            else:

                response_tokens_reply = retry_api_call(

                    client.create_tweet,

                    text=tokens_reply_text,

                    in_reply_to_tweet_id=main_tweet_id

                )

            tokens_reply_id = response_tokens_reply.data['id']

            logging.info(f"Tokens reply tweet sent successfully! Tweet ID: {tokens_reply_id}")

        else:

            logging.info("No additional tokens to display in reply tweet.")



    except Exception as e:

        logging.error(f"Critical error in tweet sending process: {e}")

        logging.error("Tweet sending failed after all retry attempts.")



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

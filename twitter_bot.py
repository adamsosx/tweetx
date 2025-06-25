import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
from tweepy import OAuth1UserHandler, API

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# API keys
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

OUTLIGHT_API_URL = "https://outlight.fun/api/tokens/most-called?timeframe=1h"

def safe_tweet_with_retry(client, text, media_ids=None, in_reply_to_tweet_id=None, max_retries=3):
    """
    Safely send tweet with rate limit handling and retry logic
    """
    for attempt in range(max_retries):
        try:
            response = client.create_tweet(
                text=text,
                media_ids=media_ids,
                in_reply_to_tweet_id=in_reply_to_tweet_id
            )
            logging.info(f"Tweet sent successfully! ID: {response.data['id']}")
            return response
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 300)  # Min 5 min buffer
            
            logging.warning(f"Rate limit exceeded. Attempt {attempt + 1}/{max_retries}")
            logging.warning(f"Waiting {wait_time} seconds before retry")
            
            if attempt < max_retries - 1:  # Don't wait on last attempt
                time.sleep(wait_time)
            else:
                logging.error("Maximum retry attempts exceeded. Tweet not sent.")
                raise e
                
        except tweepy.Forbidden as e:
            logging.error(f"Authorization error: {e}")
            raise e
            
        except tweepy.BadRequest as e:
            logging.error(f"Bad request (possibly tweet too long?): {e}")
            raise e
            
        except Exception as e:
            logging.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(30)  # Short pause before retry
    
    return None

def safe_media_upload(api_v1, image_path, max_retries=3):
    """
    Safely upload media with rate limit handling
    """
    if not os.path.isfile(image_path):
        logging.error(f"Image file not found: {image_path}")
        return None
    
    for attempt in range(max_retries):
        try:
            media = api_v1.media_upload(image_path)
            logging.info(f"Image uploaded successfully. Media ID: {media.media_id}")
            return media.media_id
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 180)
            
            logging.warning(f"Rate limit for media upload. Attempt {attempt + 1}/{max_retries}")
            logging.warning(f"Waiting {wait_time} seconds")
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logging.error("Failed to upload image after all attempts")
                return None
                
        except Exception as e:
            logging.error(f"Image upload error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(30)
    
    return None

def get_top_tokens():
    """Fetch data from outlight.fun API"""
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
        logging.error(f"Error fetching data from API: {e}")
        return None

def format_tweet(top_3_tokens):
    """Format main tweet"""
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
    """Format link tweet with variability to avoid spam detection"""
    import random
    
    # Variable prefixes
    prefixes = [
        "🧪 Data source:",
        "📊 Analytics from:",
        "🔍 Research via:",
        "📈 Insights from:",
        "🧮 Data powered by:"
    ]
    
    # Variable suffixes
    suffixes = [
        "#SOL #Outlight #TokenCalls",
        "#Solana #DeFi #TokenData",
        "#SOL #Analytics #Crypto",
        "#TokenAnalysis #SOL #Data",
        "#DeFi #Solana #TokenTracker"
    ]
    
    # Random timestamp or token count reference
    extras = [
        f"⏰ Updated hourly",
        f"📞 Live call tracking",
        f"🎯 Real-time data",
        f"⚡ Fresh insights",
        f"🔄 Auto-updated"
    ]
    
    prefix = random.choice(prefixes)
    suffix = random.choice(suffixes)
    extra = random.choice(extras)
    
    return f"{prefix} 🔗 https://outlight.fun/\n{extra}\n{suffix}"

def main():
    logging.info("GitHub Action: Bot execution started.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("Missing required API keys. Terminating.")
        return

    try:
        # Twitter API clients
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        me = client.get_me()
        logging.info(f"Successfully authenticated: @{me.data.username}")

        auth_v1 = OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        api_v1 = API(auth_v1)
        
    except Exception as e:
        logging.error(f"Error setting up Twitter clients: {e}")
        return

    # Fetch data
    top_3 = get_top_tokens()
    if not top_3:
        logging.warning("No token data available. Skipping tweet.")
        return

    # Prepare tweet texts
    tweet_text = format_tweet(top_3)
    link_tweet_text = format_link_tweet()  # No arguments needed
    
    # Validate length BEFORE any uploads
    if len(tweet_text) > 280:
        logging.error(f"Main tweet too long ({len(tweet_text)} characters). CANCELING.")
        return
    
    if len(link_tweet_text) > 280:
        logging.error(f"Reply tweet too long ({len(link_tweet_text)} characters). CANCELING.")
        return

    try:
        # STEP 1: Upload ALL images at the beginning
        logging.info("=== STEP 1: Uploading all images ===")
        
        main_image_path = os.path.join("images", "msgtwt.png")
        reply_image_path = os.path.join("images", "msgtwtft.png")
        
        # Upload first image
        logging.info("Uploading main tweet image...")
        main_media_id = safe_media_upload(api_v1, main_image_path)
        
        if not main_media_id:
            logging.error("❌ CRITICAL ERROR: Failed to upload main image.")
            logging.error("CANCELING entire process - no tweets will be sent without images.")
            return
        
        # Upload second image
        logging.info("Uploading reply tweet image...")
        reply_media_id = safe_media_upload(api_v1, reply_image_path)
        
        if not reply_media_id:
            logging.error("❌ CRITICAL ERROR: Failed to upload reply image.")
            logging.error("CANCELING entire process - no tweets will be sent without images.")
            return
            
        logging.info("✅ SUCCESS: All images uploaded successfully!")
        logging.info(f"   - Main image: Media ID {main_media_id}")
        logging.info(f"   - Reply image: Media ID {reply_media_id}")
        
        # STEP 2: Send main tweet (with image guarantee)
        logging.info("=== STEP 2: Sending main tweet with image ===")
        main_tweet_response = safe_tweet_with_retry(
            client, 
            tweet_text, 
            media_ids=[main_media_id]
        )
        
        if not main_tweet_response:
            logging.error("❌ CRITICAL ERROR: Failed to send main tweet!")
            logging.error("CANCELING: Reply will not be sent since main tweet failed.")
            return
            
        main_tweet_id = main_tweet_response.data['id']
        logging.info(f"✅ Main tweet sent with image! ID: {main_tweet_id}")
        
        # STEP 3: Safe waiting before reply
        logging.info("=== STEP 3: Waiting before reply ===")
        logging.info("Waiting 180 seconds before sending reply...")
        time.sleep(180)
        
        # STEP 4: Send reply (only if main tweet succeeded)
        logging.info("=== STEP 4: Sending reply tweet with image ===")
        logging.info("Main tweet sent successfully - proceeding with reply...")
        
        reply_response = safe_tweet_with_retry(
            client,
            link_tweet_text,
            media_ids=[reply_media_id],
            in_reply_to_tweet_id=main_tweet_id
        )
        
        if reply_response:
            logging.info(f"✅ Reply sent with image! ID: {reply_response.data['id']}")
            logging.info("🎉 FULL SUCCESS: Both tweets sent with images!")
            logging.info(f"   🔗 Main tweet: https://x.com/user/status/{main_tweet_id}")
            logging.info(f"   🔗 Reply: https://x.com/user/status/{reply_response.data['id']}")
        else:
            logging.error("❌ Failed to send reply despite successful image upload")
            logging.error(f"Main tweet was sent though: https://x.com/user/status/{main_tweet_id}")

    except Exception as e:
        logging.error(f"Unexpected error during process: {e}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    # Disable SSL warnings if verify=False is used in requests
    if 'requests' in globals():
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            logging.warning("SSL verification disabled for requests")
        except AttributeError:
            pass
    
    main()

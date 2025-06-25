import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
from tweepy import OAuth1UserHandler, API

# Try to import OpenAI - handle different versions
openai_client = None
try:
    # Try new OpenAI v1.x
    from openai import OpenAI
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        openai_client = OpenAI(api_key=openai_api_key)
        logging.info("OpenAI v1.x client initialized")
except ImportError:
    try:
        # Try old OpenAI v0.x
        import openai
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai.api_key = openai_api_key
            openai_client = "legacy"  # Flag for legacy usage
            logging.info("OpenAI v0.x client initialized")
    except ImportError:
        logging.warning("OpenAI library not available")
        openai_client = None

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
    """Format main tweet - FALLBACK if AI fails"""
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

def generate_ai_tweet(top_3_tokens):
    """Generate intelligent tweet using OpenAI based on token data"""
    if not openai_client:
        logging.warning("OpenAI client not initialized. Using fallback.")
        return format_tweet(top_3_tokens)
        
    try:
        # Prepare data for AI
        token_data = []
        for i, token in enumerate(top_3_tokens, 1):
            calls = token.get('filtered_calls', 0)
            symbol = token.get('symbol', 'Unknown')
            address = token.get('address', 'No Address')[:8] + "..."  # Shorten address
            token_data.append(f"{i}. ${symbol} - {calls} calls - {address}")
        
        data_summary = "\n".join(token_data)
        total_calls = sum(token.get('filtered_calls', 0) for token in top_3_tokens)
        
        # Create prompt for OpenAI
        system_prompt = """You are a crypto analyst responding in crypto style, in English. Use crypto slang, emojis, and engaging language that resonates with the crypto community. Be professional but use terms like 'pumping', 'calls', 'gems', 'alpha', etc. Keep it authentic to crypto Twitter culture."""
        
        prompt = f"""Create an engaging crypto Twitter post about the most called tokens in the last hour.

DATA FROM OUTLIGHT.FUN:
{data_summary}

Total calls tracked: {total_calls}

Create 1 tweet only:
- Engaging announcement about top 3 most called tokens (max 270 chars)
- Use crypto slang and style
- Include relevant emojis
- Focus on the data insights  
- Include token symbols with $ prefix
- Make it sound natural and engaging for crypto Twitter

Format your response as just the tweet text, no labels needed."""

        logging.info("Generating AI tweets...")
        
        # Handle different OpenAI versions
        if openai_client == "legacy":
            # Old OpenAI v0.x
            import openai
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.8
            )
            ai_response = response.choices[0].message.content.strip()
        else:
            # New OpenAI v1.x
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.8
            )
            ai_response = response.choices[0].message.content.strip()
        
        logging.info(f"AI Response received: {len(ai_response)} characters")
        
        # Clean up the response (remove any formatting artifacts)
        main_tweet = ai_response.strip()
        
        # Remove any potential labels that might slip through
        if main_tweet.startswith("MAIN_TWEET:"):
            main_tweet = main_tweet.replace("MAIN_TWEET:", "").strip()
        if main_tweet.startswith("Tweet:"):
            main_tweet = main_tweet.replace("Tweet:", "").strip()
        
        # Validate length
        if len(main_tweet) > 280:
            main_tweet = main_tweet[:277] + "..."
            logging.warning(f"Main tweet truncated to {len(main_tweet)} characters")
        
        if not main_tweet:
            logging.warning("Empty AI response, using fallback")
            return format_tweet(top_3_tokens)
        
        logging.info(f"✅ AI tweet generated successfully!")
        logging.info(f"   - Tweet: {len(main_tweet)} chars")
        
        return main_tweet
        
    except Exception as e:
        logging.error(f"Error generating AI tweets: {e}")
        logging.warning("Falling back to template tweets...")
        
        # Fallback to original format if AI fails
        return format_tweet(top_3_tokens)

def main():
    logging.info("GitHub Action: Bot execution started.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("Missing required Twitter API keys. Terminating.")
        return
        
    if not openai_client:
        logging.warning("OpenAI API key not found. Will use template tweets as fallback.")

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

    # Generate AI tweets or use fallback
    if openai_client:
        logging.info("=== GENERATING AI TWEET ===")
        tweet_text = generate_ai_tweet(top_3)
    else:
        logging.info("=== USING TEMPLATE TWEET ===")
        tweet_text = format_tweet(top_3)
    
    # Validate length BEFORE any uploads
    if len(tweet_text) > 280:
        logging.error(f"Main tweet too long ({len(tweet_text)} characters). CANCELING.")
        return

    logging.info(f"📝 Final tweet prepared:")
    logging.info(f"   Tweet: {len(tweet_text)} chars")

    try:
        # STEP 1: Upload single image
        logging.info("=== STEP 1: Uploading single image ===")
        
        main_image_path = os.path.join("images", "msgtwt.png")
        
        # Upload image
        logging.info("Uploading main tweet image...")
        main_media_id = safe_media_upload(api_v1, main_image_path)
        
        if not main_media_id:
            logging.error("❌ CRITICAL ERROR: Failed to upload main image.")
            logging.error("CANCELING entire process - no tweets will be sent without images.")
            return
            
        logging.info("✅ SUCCESS: Image uploaded successfully!")
        logging.info(f"   - Main image: Media ID {main_media_id}")
        
        # STEP 2: Send main tweet with image
        logging.info("=== STEP 2: Sending main tweet with image ===")
        main_tweet_response = safe_tweet_with_retry(
            client, 
            tweet_text, 
            media_ids=[main_media_id]
        )
        
        if not main_tweet_response:
            logging.error("❌ CRITICAL ERROR: Failed to send main tweet!")
            return
            
        main_tweet_id = main_tweet_response.data['id']
        logging.info(f"✅ Main tweet sent with image! ID: {main_tweet_id}")
        logging.info("🎉 SUCCESS: Tweet sent successfully!")
        logging.info(f"   🔗 Tweet: https://x.com/user/status/{main_tweet_id}")

    except Exception as e:
        logging.error(f"Unexpected error during process: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    # Disable SSL warnings if verify=False is used in requests
    try:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        logging.warning("SSL verification disabled for requests")
    except AttributeError:
        pass
    
    main()

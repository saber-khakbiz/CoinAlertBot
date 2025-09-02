import os
import time
import requests
import asyncio
from telegram import Bot
from dotenv import load_dotenv
from tokens import TOKENS

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Parse CHAT_ID - support both single ID and comma-separated multiple IDs
if not TOKEN or not CHAT_ID:
    raise Exception("Please set BOT_TOKEN and CHAT_ID in Secrets.")

# Convert CHAT_ID to list if multiple IDs are provided
if ',' in CHAT_ID:
    CHAT_IDS = [chat_id.strip() for chat_id in CHAT_ID.split(',')]
else:
    CHAT_IDS = [CHAT_ID.strip()]

print(f"📋 Bot will send messages to {len(CHAT_IDS)} chat(s)")

bot = Bot(token=TOKEN)

# File paths for custom messages
MESSAGE_FILE_PATH = "bot_messages.txt"

# USER CONFIGURABLE SETTINGS
PRICE_CHANGE_THRESHOLD = 5.0  # 5% price change
VOLUME_CHANGE_THRESHOLD = 5.0  # 5% volume change

# Timeframe settings (in seconds) - USER CONFIGURABLE
TIMEFRAMES = {
    '3min': 180,
    '15min': 900,
    '30min': 1800
}

# Settings - USER CONFIGURABLE
SEND_REGULAR_UPDATES = True  # Send price updates every cycle
SEND_ONLY_PUMPS = True      # Only send pump alerts
UPDATE_INTERVAL = 300        # Send regular updates every 5 minutes
Check_Time = 180            # Check every 3 minutes

# AUTO-CALCULATED: Maximum timeframe for memory management
MAX_TIMEFRAME = max(TIMEFRAMES.values()) if TIMEFRAMES else 900
MEMORY_RETENTION_TIME = MAX_TIMEFRAME + 300  # Keep extra 5 minutes of data

# Global variables
price_history = {}
last_update_time = 0
sent_alerts = {}  # Track sent alerts to prevent spam

def validate_settings():
    """Validate user settings and show warnings"""
    print("🔧 Validating settings...")
    
    # Check if TIMEFRAMES is not empty
    if not TIMEFRAMES:
        raise Exception("❌ TIMEFRAMES cannot be empty! Please add at least one timeframe.")
    
    # Check for invalid values
    if PRICE_CHANGE_THRESHOLD <= 0:
        raise Exception("❌ PRICE_CHANGE_THRESHOLD must be greater than 0")
    
    if Check_Time <= 0:
        raise Exception("❌ Check_Time must be greater than 0")
    
    # Check for timeframes smaller than Check_Time
    problematic_timeframes = {name: seconds for name, seconds in TIMEFRAMES.items() if seconds < Check_Time}
    if problematic_timeframes:
        print(f"⚠️  WARNING: These timeframes are smaller than Check_Time ({Check_Time}s):")
        for name, seconds in problematic_timeframes.items():
            print(f"   - {name}: {seconds}s")
        print("   This may cause inaccurate alerts in first few cycles!")
    
    # Check for very large timeframes (memory concern)
    large_timeframes = {name: seconds for name, seconds in TIMEFRAMES.items() if seconds > 7200}
    if large_timeframes:
        print(f"⚠️  WARNING: Large timeframes detected (high memory usage):")
        for name, seconds in large_timeframes.items():
            print(f"   - {name}: {seconds}s ({seconds//60} minutes)")
    
    # Check for very small Check_Time (API concern)
    if Check_Time < 60:
        print(f"⚠️  WARNING: Check_Time is {Check_Time}s. API rate limiting risk!")
        print("   Recommended: 120s or higher")
    
    # Show configuration summary
    print(f"✅ Configuration validated:")
    print(f"   📊 Monitoring {len(TIMEFRAMES)} timeframes: {list(TIMEFRAMES.keys())}")
    print(f"   ⏱️  Check interval: {Check_Time}s")
    print(f"   💾 Memory retention: {MEMORY_RETENTION_TIME}s")
    print(f"   📈 Price threshold: {PRICE_CHANGE_THRESHOLD}%")

def initialize_history_for_token(symbol):
    """Initialize price and volume history for a new token"""
    if symbol not in price_history:
        price_history[symbol] = []
    if symbol not in sent_alerts:
        sent_alerts[symbol] = {}

def update_price_history(symbol, price, volume):
    """Update price history with timestamp and data validation"""
    current_time = time.time()
    
    # Validate input data
    if not isinstance(price, (int, float)) or price <= 0:
        print(f"⚠️ Invalid price for {symbol}: {price}")
        return False
    
    if not isinstance(volume, (int, float)) or volume < 0:
        print(f"⚠️ Invalid volume for {symbol}: {volume}")
        return False
    
    # Add new price with timestamp
    price_history[symbol].append({
        'price': float(price),
        'volume': float(volume),
        'timestamp': current_time
    })
    
    # Keep only data within memory retention time
    cutoff_time = current_time - MEMORY_RETENTION_TIME
    old_count = len(price_history[symbol])
    price_history[symbol] = [
        item for item in price_history[symbol] 
        if item['timestamp'] >= cutoff_time
    ]
    
    # Clean up old alerts (older than 1 hour)
    alert_cutoff_time = current_time - 3600
    for timeframe in list(sent_alerts[symbol].keys()):
        if sent_alerts[symbol][timeframe] < alert_cutoff_time:
            del sent_alerts[symbol][timeframe]
    
    # Log memory cleanup if significant
    if old_count - len(price_history[symbol]) > 10:
        print(f"💾 Cleaned {old_count - len(price_history[symbol])} old records for {symbol}")
    
    return True

def get_price_change_for_timeframe(symbol, timeframe_seconds):
    """Get price change percentage for specific timeframe with robust error handling"""
    try:
        if symbol not in price_history or len(price_history[symbol]) < 2:
            return 0, 0
        
        current_time = time.time()
        target_time = current_time - timeframe_seconds
        
        # Get current price (latest entry)
        current_data = price_history[symbol][-1]
        current_price = current_data['price']
        current_volume = current_data['volume']
        
        # Find the closest price to target time (improved algorithm)
        old_data = None
        best_time_diff = float('inf')
        
        for data in price_history[symbol]:
            time_diff = abs(data['timestamp'] - target_time)
            if time_diff < best_time_diff:
                best_time_diff = time_diff
                old_data = data
        
        # If no suitable old data found or time difference is too large
        max_tolerance = min(timeframe_seconds * 0.5, Check_Time * 2)  # Dynamic tolerance
        if not old_data or best_time_diff > max_tolerance:
            return 0, 0
        
        old_price = old_data['price']
        old_volume = old_data['volume']
        
        # Calculate changes with robust error handling
        price_change = 0
        volume_change = 0
        
        if old_price > 0:
            price_change = ((current_price - old_price) / old_price) * 100
        
        if old_volume > 0:
            volume_change = ((current_volume - old_volume) / old_volume) * 100
        
        return price_change, volume_change
        
    except Exception as e:
        print(f"❌ Error calculating price change for {symbol}: {e}")
        return 0, 0

def should_send_alert(symbol, timeframe_name, current_time):
    """Check if alert should be sent (prevent spam)"""
    # Minimum time between alerts for same symbol and timeframe (5 minutes)
    min_alert_interval = 300
    
    if timeframe_name in sent_alerts[symbol]:
        time_since_last = current_time - sent_alerts[symbol][timeframe_name]
        if time_since_last < min_alert_interval:
            return False
    
    return True

def read_message_from_file(file_path):
    """Read message from file with proper error handling"""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                message = file.read().strip()
                if message:
                    return message
                else:
                    print(f"📄 File {file_path} is empty, no message to send")
                    return None
        else:
            print(f"📄 File {file_path} does not exist, no message to send")
            return None
    except Exception as e:
        print(f"❌ Error reading message file {file_path}: {e}")
        return None

def get_all_prices_and_volumes():
    """Fetch all token prices and volumes with better error handling"""
    if not TOKENS:
        print("⚠️ No tokens configured in TOKENS dictionary")
        return {}
    
    url = "https://api.coingecko.com/api/v3/simple/price"
    token_ids = ",".join(TOKENS.keys())
    
    params = {
        "ids": token_ids,
        "vs_currencies": "usd",
        "include_24hr_vol": "true"
    }
    
    try:
        print(f"🌐 Fetching data for {len(TOKENS)} tokens...")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print("⚠️ Empty response from API")
            return {}
        
        # Process the data and return in a structured format
        results = {}
        for cg_id, symbol in TOKENS.items():
            if cg_id in data and isinstance(data[cg_id], dict):
                price = data[cg_id].get("usd")
                volume = data[cg_id].get("usd_24h_vol")
                
                if price is not None and volume is not None and price > 0 and volume >= 0:
                    results[symbol] = {
                        "price": price,
                        "volume": volume,
                        "cg_id": cg_id
                    }
                else:
                    print(f"⚠️ Invalid price/volume data for {symbol}: price={price}, volume={volume}")
            else:
                print(f"⚠️ No valid data returned for {symbol} ({cg_id})")
        
        print(f"✅ Successfully processed {len(results)}/{len(TOKENS)} tokens")
        return results
        
    except requests.exceptions.Timeout:
        print("⛔ Request timeout while fetching prices")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"⛔ Network error fetching prices: {e}")
        return {}
    except ValueError as e:
        print(f"⛔ JSON parsing error: {e}")
        return {}
    except Exception as e:
        print(f"⛔ Unexpected error fetching prices: {e}")
        return {}

async def send_to_all_chats(message, parse_mode=None):
    """Send message to all chat IDs with better error handling"""
    if not message or not message.strip():
        print("❌ Cannot send empty message")
        return False
    
    success_count = 0
    failed_chats = []
    
    for chat_id in CHAT_IDS:
        try:
            # Validate chat_id
            if not chat_id or not chat_id.strip():
                continue
                
            if parse_mode:
                await bot.send_message(chat_id=chat_id.strip(), text=message, parse_mode=parse_mode)
            else:
                await bot.send_message(chat_id=chat_id.strip(), text=message)
            success_count += 1
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"❌ Failed to send message to {chat_id}: {e}")
            failed_chats.append(chat_id)
    
    print(f"📤 Message sent to {success_count}/{len(CHAT_IDS)} chats")
    if failed_chats:
        print(f"❌ Failed chats: {failed_chats}")
    
    return success_count > 0

async def send_price_alert(symbol, price, change_percent, volume, volume_change_percent, timeframe_name):
    """Send pump or dump alert to all Telegram chats"""
    current_time = time.time()
    
    # Check if we should send alert (prevent spam)
    if not should_send_alert(symbol, timeframe_name, current_time):
        print(f"🔇 Alert skipped for {symbol} ({timeframe_name}) - too soon since last alert")
        return False
    
    # Validate input data
    if not isinstance(change_percent, (int, float)) or not isinstance(price, (int, float)):
        print(f"❌ Invalid data for alert: {symbol}, price={price}, change={change_percent}")
        return False
    
    try:
        if change_percent > 0:
            # Pump Alert
            msg = (
                f"🚀 🟢🟢PUMP ALERT🟢🟢 🚀\n"
                f"⏰ Timeframe: {timeframe_name}\n"
                f"🔥 Token: #{symbol}\n"
                f"💰 Price: ${price:.8f}\n"
                f"📈 Price Change: +{change_percent:.2f}%\n"
                f"📊 Volume Change: {volume_change_percent:+.2f}%\n"
                f"📊 24h Volume: ${volume:,.2f}\n"
                f"🎯 **TO THE MOON!** 🌙"
            )
            alert_type = "PUMP"
        else:
            # Dump Alert
            msg = (
                f"📉 🔴🔴DUMP ALERT🔴🔴 📉\n"
                f"⏰ Timeframe: {timeframe_name}\n"
                f"💔 Token: #{symbol}\n"
                f"💰 Price: ${price:.8f}\n"
                f"📉 Price Change: {change_percent:.2f}%\n"
                f"📊 Volume Change: {volume_change_percent:+.2f}%\n"
                f"📊 24h Volume: ${volume:,.2f}\n"
                f"⚠️ **PRICE DROPPING!** ⚡"
            )
            alert_type = "DUMP"
        
        success = await send_to_all_chats(msg)
        if success:
            # Mark alert as sent
            sent_alerts[symbol][timeframe_name] = current_time
            print(f"📤 {timeframe_name} {alert_type} alert sent for {symbol}")
        return success
        
    except Exception as e:
        print(f"❌ Error sending alert for {symbol}: {e}")
        return False

async def send_message_safe(text, parse_mode=None):
    """Safely send a message to all Telegram chats"""
    try:
        return await send_to_all_chats(text, parse_mode)
    except Exception as e:
        print(f"❌ Error in send_message_safe: {e}")
        return False

async def test_bot_connection():
    """Test if bot can send messages to all chats"""
    try:
        print("🔍 Testing bot connection...")
        
        # Validate token format (basic check)
        if not TOKEN or len(TOKEN) < 10:
            print("❌ Invalid BOT_TOKEN format")
            return False
            
        print(f"📋 Bot Token: {TOKEN[:10]}...{TOKEN[-5:] if len(TOKEN) > 15 else 'SHORT'}")
        print(f"📋 Chat IDs: {CHAT_IDS}")
        
        # Test with a simple message first
        test_message = "🤖 Bot connection test successful!"
        custom_message = read_message_from_file(MESSAGE_FILE_PATH)
        
        # Try to send test message
        message_to_send = custom_message if custom_message else test_message
        success = await send_message_safe(message_to_send)
        
        if success:
            print("✅ Bot connection test successful!")
            return True
        else:
            print("❌ Bot connection test failed!")
            return False
            
    except Exception as e:
        print(f"❌ Bot connection test failed: {e}")
        print("💡 Please check:")
        print("   1. BOT_TOKEN is correct")
        print("   2. CHAT_IDs are correct") 
        print("   3. Bot has been started in all Telegram chats (/start)")
        print("   4. Bot is not blocked in any chat")
        return False

async def send_regular_update(data):
    """Send regular price update to all chats"""
    global last_update_time
    
    try:
        current_time = time.time()
        
        # Only send regular updates if enabled and interval has passed
        if not SEND_REGULAR_UPDATES or (current_time - last_update_time) < UPDATE_INTERVAL:
            return
        
        if not data:
            print("⚠️ No data available for regular update")
            return
        
        msg_parts = ["📊 **Price Update:**\n"]
        
        # Get smallest timeframe for regular updates
        smallest_timeframe = min(TIMEFRAMES.values())
        
        for symbol, info in data.items():
            price = info["price"]
            
            # Get price change for smallest timeframe
            price_change, _ = get_price_change_for_timeframe(symbol, smallest_timeframe)
            
            # Choose emoji based on price change
            if price_change > 2:
                emoji = "🟢"
            elif price_change < -2:
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            msg_parts.append(f"{emoji} **{symbol}**: ${price:.8f} ({price_change:+.2f}%)")
        
        msg_parts.append(f"\n🕐 Updated: {time.strftime('%H:%M:%S')}")
        
        await send_to_all_chats("\n".join(msg_parts), parse_mode='Markdown')
        last_update_time = current_time
        print("📤 Regular update sent to all chats")
        
    except Exception as e:
        print(f"❌ Error sending regular update: {e}")

async def check_tokens():
    """Check all tokens for pump signals across multiple timeframes"""
    print("🔁 Fetching all token data...")
    
    # Get all prices and volumes in one API call
    current_data = get_all_prices_and_volumes()
    
    if not current_data:
        print("❌ No data received from API")
        return
    
    print(f"✅ Successfully fetched data for {len(current_data)} tokens")
    
    alerts_sent = 0
    current_time = time.time()
    
    for symbol, data in current_data.items():
        try:
            price = data["price"]
            volume = data["volume"]
            
            # Initialize history if first time seeing this token
            initialize_history_for_token(symbol)
            
            # Update price history
            if not update_price_history(symbol, price, volume):
                continue
            
            # Check each timeframe for significant changes
            for timeframe_name, timeframe_seconds in TIMEFRAMES.items():
                try:
                    price_change, volume_change = get_price_change_for_timeframe(symbol, timeframe_seconds)
                    
                    # Only log if we have meaningful data
                    if price_change != 0 or len(price_history[symbol]) > 1:
                        print(f"💰 {symbol} ({timeframe_name}): ${price:.8f} (Price: {price_change:+.2f}%, Volume: {volume_change:+.2f}%)")
                    
                    # Check for pump/dump conditions
                    if abs(price_change) >= PRICE_CHANGE_THRESHOLD:
                        # Additional check: only send if we have enough data points
                        if len(price_history[symbol]) >= 2:
                            if await send_price_alert(symbol, price, price_change, volume, volume_change, timeframe_name):
                                alerts_sent += 1
                        else:
                            print(f"⏳ Insufficient data for {symbol} ({timeframe_name}) - need more history")
                
                except Exception as e:
                    print(f"❌ Error processing timeframe {timeframe_name} for {symbol}: {e}")
                    continue
        
        except Exception as e:
            print(f"❌ Error processing token {symbol}: {e}")
            continue
    
    if alerts_sent > 0:
        print(f"🎯 Sent {alerts_sent} price alerts to all chats")
    else:
        print("😴 No significant price changes detected this round")
    
    # Send regular updates if enabled
    if SEND_REGULAR_UPDATES and not SEND_ONLY_PUMPS:
        await send_regular_update(current_data)

async def main_async():
    """Main async bot loop with comprehensive error handling"""
    try:
        # Validate settings before starting
        validate_settings()
        
        # Test bot connection first
        if not await test_bot_connection():
            print("🛑 Stopping due to connection issues")
            return
        
        print("🚀 Bot started successfully!")
        print(f"📊 Monitoring timeframes: {list(TIMEFRAMES.keys())}")
        print(f"⏱️ Check interval: {Check_Time} seconds")
        print(f"📈 Price threshold: {PRICE_CHANGE_THRESHOLD}%")
        
        # Main monitoring loop
        cycle_count = 0
        while True:
            cycle_count += 1
            print(f"\n{'='*50}")
            print(f"🕐 Cycle #{cycle_count} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                await check_tokens()
            except Exception as e:
                print(f"❌ Error in check cycle #{cycle_count}: {e}")
                # Send error notification
                try:
                    await send_message_safe(f"⚠️ Bot cycle error #{cycle_count}: {str(e)[:80]}...")
                except:
                    pass  # Don't crash on notification failure
            
            print(f"⏳ Waiting {Check_Time} seconds for next check...")
            
            # Use smaller sleep intervals to allow for interruption
            for i in range(Check_Time):
                await asyncio.sleep(1)
                if i % 30 == 0 and i > 0:  # Progress indicator every 30 seconds
                    remaining = Check_Time - i
                    print(f"⏳ {remaining}s remaining...")
            
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        try:
            stop_message = read_message_from_file(MESSAGE_FILE_PATH)
            if stop_message:
                await send_message_safe(stop_message)
            else:
                await send_message_safe("🛑 Crypto monitoring bot stopped")
        except:
            pass
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        try:
            await send_message_safe(f"💥 Bot crashed: {str(e)[:100]}...")
        except:
            pass

def main():
    """Main function to run the async bot with top-level error handling"""
    try:
        print("🔄 Starting Crypto Monitoring Bot...")
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"💥 Fatal error in main: {e}")
        print("💡 Check your configuration and try again")

if __name__ == "__main__":
    main()


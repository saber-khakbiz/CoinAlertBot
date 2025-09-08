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

# Thresholds for alerts
PRICE_CHANGE_THRESHOLD = 5.0  # 5% price change
VOLUME_CHANGE_THRESHOLD = 5.0  # 5% volume change

# Settings
SEND_REGULAR_UPDATES = False  # حذف پیام‌های Price Update
SEND_ONLY_PUMPS = False  # تغییر شد: False تا dump alert هم ارسال شود
UPDATE_INTERVAL = 300
CHECK_INTERVAL = 120  # Check API every 2 minutes (safe from rate limiting)

# Multi-timeframe settings
TIMEFRAMES = {
    "3min": 180,   # 3 minutes in seconds
    "5min": 300,   # 5 minutes in seconds
    "15min": 900   # 15 minutes in seconds
}

# Storage for historical data for each timeframe
timeframe_data = {
    "3min": {"prices": {}, "volumes": {}, "last_check": 0},
    "5min": {"prices": {}, "volumes": {}, "last_check": 0},
    "15min": {"prices": {}, "volumes": {}, "last_check": 0},
}

last_update_time = 0
startup_time = time.time()

def read_message_from_file(file_path):
    """
    خواندن پیام از فایل مشخص شده
    اگر فایل وجود نداشته باشد یا خالی باشد، None برمی‌گرداند
    """
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
    """Fetch all token prices and volumes in a single API call"""
    url = "https://api.coingecko.com/api/v3/simple/price"
    
    # Validate TOKENS dictionary
    if not TOKENS:
        print("❌ TOKENS dictionary is empty")
        return {}
    
    token_ids = ",".join(TOKENS.keys())
    
    params = {
        "ids": token_ids,
        "vs_currencies": "usd",
        "include_24hr_vol": "true",
        "include_market_cap": "true"  # اضافه کردن market cap
    }
    
    try:
        print(f"🌐 Requesting data from CoinGecko API...")
        response = requests.get(url, params=params, timeout=15)  # افزایش timeout
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print("⚠️ Empty response from API")
            return {}
        
        results = {}
        total_market_cap = 0  # برای محاسبه مجموع market cap
        
        for cg_id, symbol in TOKENS.items():
            if cg_id in data:
                token_data = data[cg_id]
                price = token_data.get("usd")
                volume = token_data.get("usd_24h_vol")
                market_cap = token_data.get("usd_market_cap")
                
                if price is not None and volume is not None:
                    results[symbol] = {
                        "price": float(price),  # اطمینان از نوع داده
                        "volume": float(volume),
                        "market_cap": float(market_cap) if market_cap is not None else 0,
                        "cg_id": cg_id
                    }
                    # اضافه کردن به مجموع market cap
                    if market_cap is not None:
                        total_market_cap += float(market_cap)
                else:
                    print(f"⚠️ Missing price or volume data for {symbol}")
            else:
                print(f"⚠️ No data returned for {symbol} ({cg_id})")
        
        # اضافه کردن total market cap به نتایج
        if results:
            results["_total_market_cap"] = total_market_cap
        
        print(f"✅ Successfully fetched data for {len(results)} tokens")
        print(f"💰 Total Market Cap: ${total_market_cap:,.2f}")
        return results
        
    except requests.exceptions.Timeout:
        print("⛔ Request timeout while fetching prices (15s)")
        return {}
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print("⛔ Rate limited by API. Increase CHECK_INTERVAL!")
        else:
            print(f"⛔ HTTP error fetching prices: {e}")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"⛔ Network error fetching prices: {e}")
        return {}
    except Exception as e:
        print(f"⛔ Unexpected error fetching prices: {e}")
        return {}

async def send_to_all_chats(message, parse_mode=None):
    """Send message to all chat IDs with better error handling"""
    success_count = 0
    failed_chats = []
    
    for chat_id in CHAT_IDS:
        try:
            # اعتبارسنجی chat_id
            if not chat_id.strip():
                print(f"⚠️ Empty chat ID, skipping")
                continue
                
            if parse_mode:
                await bot.send_message(chat_id=chat_id, text=message, parse_mode=parse_mode)
            else:
                await bot.send_message(chat_id=chat_id, text=message)
            success_count += 1
            # افزایش تاخیر برای جلوگیری از rate limiting
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ Failed to send message to {chat_id}: {e}")
            failed_chats.append(chat_id)
    
    print(f"📤 Message sent to {success_count}/{len(CHAT_IDS)} chats")
    if failed_chats:
        print(f"❌ Failed chats: {failed_chats}")
    
    return success_count > 0

async def send_price_alert(symbol, price, change_percent, volume, volume_change_percent, timeframe, market_cap=None, total_market_cap=None):
    """Send pump or dump alert to all Telegram chats with timeframe info and market cap"""
    
    # اعتبارسنجی ورودی‌ها
    if not symbol or price <= 0:
        print(f"❌ Invalid data for alert: symbol={symbol}, price={price}")
        return False
    
    # تعیین فرمت قیمت بر اساس مقدار
    if price < 0.0001:
        price_format = f"${price:.10f}"
    elif price < 0.01:
        price_format = f"${price:.8f}"
    elif price < 1:
        price_format = f"${price:.6f}"
    else:
        price_format = f"${price:.4f}"
    
    # فرمت market cap
    market_cap_text = ""
    if market_cap and market_cap > 0:
        if market_cap >= 1e9:
            market_cap_text = f"\n💎 Market Cap: ${market_cap/1e9:.2f}B"
        elif market_cap >= 1e6:
            market_cap_text = f"\n💎 Market Cap: ${market_cap/1e6:.2f}M"
        else:
            market_cap_text = f"\n💎 Market Cap: ${market_cap:,.0f}"
    
    # فرمت total market cap
    total_market_cap_text = ""
    if total_market_cap and total_market_cap > 0:
        if total_market_cap >= 1e9:
            total_market_cap_text = f"\n🏆 Total Portfolio Cap: ${total_market_cap/1e9:.2f}B"
        elif total_market_cap >= 1e6:
            total_market_cap_text = f"\n🏆 Total Portfolio Cap: ${total_market_cap/1e6:.2f}M"
        else:
            total_market_cap_text = f"\n🏆 Total Portfolio Cap: ${total_market_cap:,.0f}"
    
    if change_percent > 0:
        # Pump Alert
        msg = (
            f"🚀 🟢🟢PUMP ALERT🟢🟢 🚀\n"
            f"⏰ Timeframe: {timeframe}\n"
            f"🔥 Token: #{symbol}\n"
            f"💰 Price: {price_format}\n"
            f"📈 Price Change: +{change_percent:.2f}%\n"
            f"📊 Volume Change: {volume_change_percent:+.2f}%\n"
            f"📊 24h Volume: ${volume:,.2f}"
            f"{market_cap_text}"
            f"{total_market_cap_text}\n"
            f"🎯 **TO THE MOON!** 🌙"
        )
        alert_type = "PUMP"
    else:
        # Dump Alert
        msg = (
            f"📉 🔴🔴DUMP ALERT🔴🔴 📉\n"
            f"⏰ Timeframe: {timeframe}\n"
            f"💔 Token: #{symbol}\n"
            f"💰 Price: {price_format}\n"
            f"📉 Price Change: {change_percent:.2f}%\n"
            f"📊 Volume Change: {volume_change_percent:+.2f}%\n"
            f"📊 24h Volume: ${volume:,.2f}"
            f"{market_cap_text}"
            f"{total_market_cap_text}\n"
            f"⚠️ **PRICE DROPPING!** ⚡️"
        )
        alert_type = "DUMP"
    
    try:
        success = await send_to_all_chats(msg)
        if success:
            print(f"📤 {alert_type} alert sent for {symbol} ({timeframe})")
        return success
    except Exception as e:
        print(f"❌ Error sending {alert_type} alert for {symbol}: {e}")
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
        print(f"📋 Bot Token: {TOKEN[:10]}...{TOKEN[-5:] if len(TOKEN) > 15 else 'INVALID'}")
        print(f"📋 Chat IDs: {CHAT_IDS}")
        
        test_message = read_message_from_file(MESSAGE_FILE_PATH)
        
        if test_message:
            success = await send_message_safe(test_message)
            if success:
                print("✅ Bot connection test successful!")
                return True
            else:
                print("❌ Bot connection test failed!")
                return False
        else:
            print("✅ Bot connection verified (no test message to send)")
            return True
            
    except Exception as e:
        print(f"❌ Bot connection test failed: {e}")
        print("💡 Please check:")
        print("   1. BOT_TOKEN is correct")
        print("   2. CHAT_IDs are correct") 
        print("   3. Bot has been started in all Telegram chats (/start)")
        print("   4. Bot is not blocked in any chat")
        return False

def should_check_timeframe(timeframe, current_time):
    """Check if we should analyze this timeframe based on current time"""
    tf_data = timeframe_data[timeframe]
    interval = TIMEFRAMES[timeframe]
    
    # در startup اولیه، همه تایم‌فریم‌ها رو چک نکن
    if current_time - startup_time < interval:
        return False
    
    # اگر هیچ چک قبلی نداریم، چک کن
    if tf_data["last_check"] == 0:
        return True
    
    # چک کن که آیا زمان کافی گذشته
    return (current_time - tf_data["last_check"]) >= interval

def update_timeframe_data(timeframe, current_data, current_time):
    """Update historical data for a specific timeframe"""
    tf_data = timeframe_data[timeframe]
    
    for symbol, data in current_data.items():
        # پرهیز از ذخیره کردن total market cap در داده های تاریخی
        if symbol != "_total_market_cap":
            tf_data["prices"][symbol] = data["price"]
            tf_data["volumes"][symbol] = data["volume"]
    
    tf_data["last_check"] = current_time

def get_price_changes(timeframe, current_data):
    """Calculate price and volume changes for a specific timeframe"""
    tf_data = timeframe_data[timeframe]
    changes = {}
    
    for symbol, current_info in current_data.items():
        # پرهیز از پردازش total market cap
        if symbol == "_total_market_cap":
            continue
            
        current_price = current_info["price"]
        current_volume = current_info["volume"]
        
        old_price = tf_data["prices"].get(symbol)
        old_volume = tf_data["volumes"].get(symbol)
        
        if old_price is not None and old_volume is not None and old_price > 0 and old_volume > 0:
            try:
                price_change = ((current_price - old_price) / old_price) * 100
                volume_change = ((current_volume - old_volume) / old_volume) * 100
                
                changes[symbol] = {
                    "price_change": price_change,
                    "volume_change": volume_change,
                    "current_price": current_price,
                    "current_volume": current_volume,
                    "market_cap": current_info.get("market_cap", 0)
                }
            except ZeroDivisionError:
                print(f"⚠️ Division by zero for {symbol} in {timeframe}")
                continue
    
    return changes

async def check_timeframe(timeframe, current_data, current_time):
    """Check a specific timeframe for alerts"""
    print(f"🔍 Checking {timeframe} timeframe...")
    
    # Get price changes for this timeframe
    changes = get_price_changes(timeframe, current_data)
    
    if not changes:
        print(f"⚠️ No historical data available for {timeframe} comparison")
        update_timeframe_data(timeframe, current_data, current_time)
        return 0
    
    alerts_sent = 0
    total_market_cap = current_data.get("_total_market_cap", 0)
    
    for symbol, change_data in changes.items():
        price_change = change_data["price_change"]
        volume_change = change_data["volume_change"]
        current_price = change_data["current_price"]
        current_volume = change_data["current_volume"]
        market_cap = change_data.get("market_cap", 0)
        
        print(f"💰 {symbol} ({timeframe}): Price: {price_change:+.2f}%, Volume: {volume_change:+.2f}%")
        
        # چک کردن تغییرات قیمت معنادار
        if abs(price_change) >= PRICE_CHANGE_THRESHOLD:
            try:
                if await send_price_alert(symbol, current_price, price_change, current_volume, volume_change, timeframe, market_cap, total_market_cap):
                    alerts_sent += 1
                    # تاخیر بین ارسال هر alert
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"❌ Error sending alert for {symbol}: {e}")
    
    # به‌روزرسانی داده‌های تایم‌فریم بعد از چک
    update_timeframe_data(timeframe, current_data, current_time)
    
    if alerts_sent > 0:
        print(f"🎯 Sent {alerts_sent} alerts for {timeframe} timeframe")
    else:
        print(f"😴 No significant changes in {timeframe} timeframe")
    
    return alerts_sent

async def send_regular_update(data):
    """Send regular price update to all chats"""
    global last_update_time
    current_time = time.time()
    
    # Only send regular updates if enabled and interval has passed
    if not SEND_REGULAR_UPDATES or (current_time - last_update_time) < UPDATE_INTERVAL:
        return
    
    if not data:
        return
    
    msg_parts = ["📊 **Price Update:**\n"]
    total_market_cap = data.get("_total_market_cap", 0)
    
    try:
        for symbol, info in data.items():
            # پرهیز از نمایش total market cap در لیست توکن ها
            if symbol == "_total_market_cap":
                continue
                
            price = info["price"]
            market_cap = info.get("market_cap", 0)
            
            # فرمت بهتر برای قیمت
            if price < 0.0001:
                price_str = f"${price:.10f}"
            elif price < 0.01:
                price_str = f"${price:.8f}"
            else:
                price_str = f"${price:.6f}"
            
            # فرمت market cap
            if market_cap >= 1e9:
                cap_str = f"({market_cap/1e9:.2f}B)"
            elif market_cap >= 1e6:
                cap_str = f"({market_cap/1e6:.2f}M)"
            elif market_cap > 0:
                cap_str = f"(${market_cap:,.0f})"
            else:
                cap_str = ""
            
            msg_parts.append(f"💰 **{symbol}**: {price_str} {cap_str}")
        
        # اضافه کردن total market cap
        if total_market_cap > 0:
            if total_market_cap >= 1e9:
                total_cap_str = f"${total_market_cap/1e9:.2f}B"
            elif total_market_cap >= 1e6:
                total_cap_str = f"${total_market_cap/1e6:.2f}M"
            else:
                total_cap_str = f"${total_market_cap:,.0f}"
            msg_parts.append(f"\n🏆 **Total Portfolio Cap**: {total_cap_str}")
        
        msg_parts.append(f"\n🕐 Updated: {time.strftime('%H:%M:%S')}")
        
        await send_to_all_chats("\n".join(msg_parts), parse_mode='Markdown')
        last_update_time = current_time
        print("📤 Regular update sent to all chats")
    except Exception as e:
        print(f"❌ Error sending regular update: {e}")

async def check_all_timeframes():
    """Check all tokens across multiple timeframes"""
    print("🔁 Fetching current token data...")
    
    current_data = get_all_prices_and_volumes()
    
    if not current_data:
        print("❌ No data received from API")
        return
    
    current_time = time.time()
    total_alerts = 0
    
    # Check each timeframe
    for timeframe in TIMEFRAMES.keys():
        try:
            if should_check_timeframe(timeframe, current_time):
                alerts = await check_timeframe(timeframe, current_data, current_time)
                total_alerts += alerts
            else:
                remaining_time = TIMEFRAMES[timeframe] - (current_time - timeframe_data[timeframe]["last_check"])
                print(f"⏭️ Skipping {timeframe} timeframe (next check in {remaining_time/60:.1f} min)")
        except Exception as e:
            print(f"❌ Error checking {timeframe}: {e}")
    
    # Initialize empty timeframes (first run)
    for timeframe in TIMEFRAMES.keys():
        tf_data = timeframe_data[timeframe]
        if not tf_data["prices"]:
            update_timeframe_data(timeframe, current_data, current_time)
            print(f"🔄 Initialized {timeframe} timeframe data")
    
    # Send regular updates if enabled
    if SEND_REGULAR_UPDATES and not SEND_ONLY_PUMPS:
        await send_regular_update(current_data)
    
    if total_alerts > 0:
        print(f"🎯 Total alerts sent: {total_alerts}")
    else:
        print("😴 No alerts sent this cycle")

async def main_async():
    """Main async bot loop"""
    if not await test_bot_connection():
        print("🛑 Stopping due to connection issues")
        return
    
    try:        
        print("🚀 Multi-timeframe bot started successfully!")
        print(f"📊 Monitoring timeframes: {list(TIMEFRAMES.keys())}")
        print(f"⏱️ Check interval: {CHECK_INTERVAL} seconds")
        print(f"🎯 Price change threshold: {PRICE_CHANGE_THRESHOLD}%")
        print(f"📈 Monitoring {len(TOKENS)} tokens")
        
        cycle_count = 0
        
        while True:
            cycle_count += 1
            print(f"\n{'='*60}")
            print(f"🕐 Check cycle #{cycle_count} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                await check_all_timeframes()
            except Exception as e:
                print(f"❌ Error in check cycle: {e}")
                # ارسال خطا فقط برای خطاهای مهم
                if "rate limit" in str(e).lower() or "connection" in str(e).lower():
                    await send_message_safe(f"⚠️ Bot error: {str(e)[:100]}...")
            
            print(f"⏳ Waiting {CHECK_INTERVAL} seconds for next check...")
            await asyncio.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        stop_message = read_message_from_file(MESSAGE_FILE_PATH)
        if stop_message:
            await send_message_safe(stop_message)
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        await send_message_safe(f"💥 Bot crashed: {str(e)[:100]}...")

def main():
    """Main function to run the async bot"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"💥 Fatal error in main: {e}")

if __name__ == "__main__":
    main()
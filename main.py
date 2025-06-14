import os
import time
import requests
import asyncio
from telegram import Bot
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Ensure BOT_TOKEN and CHAT_ID are set in the environment variables
if not TOKEN or not CHAT_ID:
    raise Exception("Please set BOT_TOKEN and CHAT_ID in Secrets.")

bot = Bot(token=TOKEN)

TOKENS = {
    "bitcoin": "BTC",
    "dogecoin": "DOGE",
    "baby-doge-coin": "BABYDOGE",
    "terra-luna": "LUNA",
    "shiba-inu": "SHIB",
    "ripple": "XRP",
    "dogs-2":"DOGS",
    "x-empire":"X Empire",
    "aura-on-sol":"Aura",
    "tron":"Tron",
    "pi-network":"PI",
    "aptos":"Aptos",
    "stupidcoin-2":"STUPID",
    "jupiter-exchange-solana":"JUPITER",
    "shiba-inu":"Shiba",
    "solana":"Solana",
    "the-open-network":"Ton",
    "pudgy-penguins":"Pudgy Penguins",
    "polkadot":"Polkadot",
    "sonic-3":"SONIC",
    "stellar":"Stellar",
    "polygon-ecosystem-token":"PLYGON",
    "official-trump":"TRUMP",
    "baby-doge-coin":"Baby-Doge",
    "pancakeswap-token":"CAKE",
    "solayer":"Layer",
    "xen-crypto":"Xen",
    "pepe":"PEPE",
    "pax-gold":"PAXG",
    
}

# Thresholds for alerts
PRICE_CHANGE_THRESHOLD = 5.0  # 5% price change
VOLUME_CHANGE_THRESHOLD = 5.0  # 5% volume change

# Settings
SEND_REGULAR_UPDATES = True  # Send price updates every cycle
SEND_ONLY_PUMPS = True      # Only send pump alerts
UPDATE_INTERVAL = 300        # Send regular updates every 5 minutes (300 seconds)
Check_Time  = 300             # Send request to API every 1 minutes (60 seconds)

last_prices = {}
last_volumes = {}
last_update_time = 0

def get_all_prices_and_volumes():
    """Fetch all token prices and volumes in a single API call"""
    url = "https://api.coingecko.com/api/v3/simple/price"
    
    # Join all token IDs into a single comma-separated string
    token_ids = ",".join(TOKENS.keys())
    
    params = {
        "ids": token_ids,
        "vs_currencies": "usd",
        "include_24hr_vol": "true"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Process the data and return in a structured format
        results = {}
        for cg_id, symbol in TOKENS.items():
            if cg_id in data:
                price = data[cg_id].get("usd")
                volume = data[cg_id].get("usd_24h_vol")
                if price is not None and volume is not None:
                    results[symbol] = {
                        "price": price,
                        "volume": volume,
                        "cg_id": cg_id
                    }
                else:
                    print(f"⚠️ Missing price or volume data for {symbol}")
            else:
                print(f"⚠️ No data returned for {symbol} ({cg_id})")
        
        return results
        
    except requests.exceptions.Timeout:
        print("⛔ Request timeout while fetching prices")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"⛔ Network error fetching prices: {e}")
        return {}
    except Exception as e:
        print(f"⛔ Unexpected error fetching prices: {e}")
        return {}

async def send_pump_alert(symbol, price, change_percent, volume, volume_change_percent):
    """Send pump alert to Telegram"""
    msg = (
        f"🚀 Pump detected in 1 minute!\n"
        f"🔹 Token: {symbol}\n"
        f"💰 Price: ${price:.8f}\n"
        f"📈 Price Change: {change_percent:.2f}%\n"
        f"📊 Volume Change: {volume_change_percent:.2f}%\n"
        f"📊 24h Volume: ${volume:,.2f}"
    )
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        print(f"📤 Alert sent for {symbol}")
        return True
    except Exception as e:
        print(f"❌ Error sending message for {symbol}: {e}")
        return False

async def send_message_safe(text):
    """Safely send a message to Telegram"""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
        return True
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False

async def test_bot_connection():
    """Test if bot can send messages"""
    try:
        print("🔍 Testing bot connection...")
        print(f"📋 Bot Token: {TOKEN[:10]}...{TOKEN[-5:] if len(TOKEN) > 15 else 'INVALID'}")
        print(f"📋 Chat ID: {CHAT_ID}")
        
        # Test message
        success = await send_message_safe("🔧 Bot connection test - If you see this, everything works!")
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
        print("   2. CHAT_ID is correct") 
        print("   3. Bot has been started in Telegram (/start)")
        print("   4. Bot is not blocked")
        return False

async def send_regular_update(data):
    """Send regular price update"""
    global last_update_time
    current_time = time.time()
    
    # Only send regular updates if enabled and interval has passed
    if not SEND_REGULAR_UPDATES or (current_time - last_update_time) < UPDATE_INTERVAL:
        return
    
    msg_parts = ["📊 **Price Update:**\n"]
    
    for symbol, info in data.items():
        price = info["price"]
        volume = info["volume"]
        
        old_price = last_prices.get(symbol, price)
        price_change = ((price - old_price) / old_price) * 100 if old_price != 0 else 0
        
        # Choose emoji based on price change
        if price_change > 0:
            emoji = "🟢"
        elif price_change < 0:
            emoji = "🔴"
        else:
            emoji = "⚪"
        
        msg_parts.append(f"{emoji} **{symbol}**: ${price:.10f} ({price_change:+.2f}%)")
    
    msg_parts.append(f"\n🕐 Updated: {time.strftime('%H:%M:%S')}")
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text="\n".join(msg_parts), parse_mode='Markdown')
        last_update_time = current_time
        print("📤 Regular update sent")
    except Exception as e:
        print(f"❌ Error sending regular update: {e}")

async def check_tokens():
    """Check all tokens for pump signals"""
    print("🔁 Fetching all token data...")
    
    # Get all prices and volumes in one API call
    current_data = get_all_prices_and_volumes()
    
    if not current_data:
        print("❌ No data received from API")
        return
    
    print(f"✅ Successfully fetched data for {len(current_data)} tokens")
    
    alerts_sent = 0
    
    for symbol, data in current_data.items():
        price = data["price"]
        volume = data["volume"]
        
        # Get previous values
        old_price = last_prices.get(symbol, price)
        old_volume = last_volumes.get(symbol, volume)
        
        # Calculate percentage changes
        price_change = ((price - old_price) / old_price) * 100 if old_price != 0 else 0
        volume_change = ((volume - old_volume) / old_volume) * 100 if old_volume != 0 else 0
        
        print(f"💰 {symbol}: ${price:.10f} (Price: {price_change:+.2f}%, Volume: {volume_change:+.2f}%)")
        
        # For testing purposes, let's also check smaller changes
        # Remove this after testing
        #if abs(price_change) >= 1.0 or abs(volume_change) >= 1.0:
        #   print(f"🔍 {symbol} shows change - Price: {price_change:.2f}%, Volume: {volume_change:.2f}%")
        
        # Check for pump conditions
        if price_change >= PRICE_CHANGE_THRESHOLD and volume_change >= VOLUME_CHANGE_THRESHOLD:
            if await send_pump_alert(symbol, price, price_change, volume, volume_change):
                alerts_sent += 1
        
        # Update stored values
        last_prices[symbol] = price
        last_volumes[symbol] = volume
    
    if alerts_sent > 0:
        print(f"🎯 Sent {alerts_sent} pump alerts")
    else:
        print("😴 No pumps detected this round")
    
    # Send regular updates if enabled
    if SEND_REGULAR_UPDATES and not SEND_ONLY_PUMPS:
        await send_regular_update(current_data)

async def main_async():
    """Main async bot loop"""
    # Test bot connection first
    if not await test_bot_connection():
        print("🛑 Stopping due to connection issues")
        return
    
    try:
        # Send startup message
        await send_message_safe("🤖 Crypto pump detector started successfully!")
        print("🚀 Bot started successfully!")
        
        # Main monitoring loop
        while True:
            print(f"\n{'='*50}")
            print(f"🕐 Starting check cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                await check_tokens()
            except Exception as e:
                print(f"❌ Error in check cycle: {e}")
                # Send error notification (optional)
                await send_message_safe(f"⚠️ Bot error: {str(e)[:100]}...")
            
            print(f"⏳ Waiting {Check_Time} seconds for next check...")
            await asyncio.sleep(Check_Time)
            
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        await send_message_safe("🛑 Crypto pump detector stopped")
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        await send_message_safe(f"💥 Bot crashed: {str(e)[:100]}...")

def main():
    """Main function to run the async bot"""
    try:
        # Run the async main function
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"💥 Fatal error in main: {e}")

if __name__ == "__main__":
    main()

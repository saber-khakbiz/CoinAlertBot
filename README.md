# Telegram Crypto Bot

A simple Telegram bot that fetches Bitcoin price every minute and sends it to your Telegram chat.

## 📦 Requirements

- python-telegram-bot==20.6
- requests
- python-dotenv

## ⚙️ Environment Variables

Make sure to define the following variables in your `.env` file or in Railway:

- `BOT_TOKEN`
- `CHAT_ID`

## 🚀 Deployment

1. Push this project to a GitHub repo.
2. Connect the repo to [Railway](https://railway.app).
3. Add environment variables.
4. Done! Your bot will now run 24/7 (with UptimeRobot if needed).

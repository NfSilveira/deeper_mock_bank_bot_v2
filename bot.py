import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

## Fetching the Bot Token and MongoDB URI from an independent .env file, for security reasons
load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
mongo_uri = os.getenv("MONGODB_URI")

if not bot_token:

    raise ValueError("Missing TELEGRAM_BOT_TOKEN! Check your .env file.")

if not mongo_uri:

    raise ValueError("Missing MONGODB_URI! Check your .env file.")


## Setting up the MongoDB Connection
client = MongoClient(mongo_uri)
db = client["mock_bank"]
users_collection = db["users"]


## Setting up Logging for Debugging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)


async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message or update.callback_query.message ## Handling the bot's initial message, as well as returns to the main menu

    keyboard_options = [
        [InlineKeyboardButton("Check my Account Balance", callback_data="check_balance")],
        [InlineKeyboardButton("Deposit", callback_data="deposit")],
        [InlineKeyboardButton("Withdraw", callback_data="withdraw")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard_options)

    await message.reply_text("Welcome to the Deeper Mock Bank! What would you like to do today?", reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    try:

        if not user:

            users_collection.insert_one({"user_id": user_id, "balance": 0, "last_transaction": None})
            user = users_collection.find_one({"user_id": user_id})

        if query.data == "check_balance":

            last_transaction = user.get("last_transaction")
            last_transaction_response = (f"Your last transaction was of ${last_transaction["amount"]} at {last_transaction["time"]} ."
            if last_transaction else "No transactions have been made yet.")

            keyboard_options = [
                [InlineKeyboardButton("Return to Main Menu", callback_data="return_main")],
                [InlineKeyboardButton("Exit", callback_data="exit_bot")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard_options)
            
            await query.message.reply_text(
                f"Your balance is ${user['balance']}\n{last_transaction_response} Is there anything else I can help you with?",
                reply_markup=reply_markup
            )

        elif query.data == "deposit":

            await query.message.reply_text("Enter the amount to be deposited:")
            context.user_data["action"] = "deposit"

        elif query.data == "withdraw":

            await query.message.reply_text("Enter the amount to be withdrawn:")
            context.user_data["action"] = "withdraw"

        elif query.data == "return_main":

            await start_bot(update, context)  ## Restart the menu when the "Return to Main Menu" option is selected

        elif query.data == "exit_bot":

            await query.message.reply_text("Thank you for using the Deeper Mock Banking Bot! Have a great day! \U0001F44B")

    except Exception as e:

        logging.error(f"Error in button function: {e}")
        await query.message.reply_text("An unexpected error occurred. Returning to the main menu.")
        await start_bot(update, context)

    await query.answer()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    user = users_collection.find_one({"user_id": user_id})
    action = context.user_data.get("action")

    if action in ["deposit", "withdraw"]:

        try:

            amount = int(update.message.text)
            if amount <= 0:

                await update.message.reply_text("The amount must be greater than zero. Please try again:")
                return
            
            if action == "withdraw" and amount > user["balance"]:

                await update.message.reply_text("Insufficient balance. Please try again:")
                return

            context.user_data["amount"] = amount
            keyboard_options = [
                [InlineKeyboardButton("Confirm", callback_data="confirm")],
                [InlineKeyboardButton("Cancel", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard_options)

            await update.message.reply_text(f"Confirm {action} of ${amount}?", reply_markup=reply_markup)

        except ValueError:

            await update.message.reply_text("Invalid number. Please try again:")


async def confirm_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id
    action = context.user_data.get("action")
    amount = context.user_data.get("amount")

    if query.data == "confirm" and action and amount:

        user = users_collection.find_one({"user_id": user_id})
        new_balance = user["balance"] + amount if action == "deposit" else user["balance"] - amount
        users_collection.update_one({"user_id": user_id}, {"$set": {"balance": new_balance, "last_transaction": {"amount": amount, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}})
        
        await query.message.reply_text(f"{action.capitalize()} successful! Current Balance: ${new_balance}")

    else:
        await query.message.reply_text("Transaction Cancelled.")

    await query.answer()

    keyboard_options = [
        [InlineKeyboardButton("Return to Main Menu", callback_data="return_main")],
        [InlineKeyboardButton("Exit", callback_data="exit_bot")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard_options)
    
    await query.message.reply_text("Is there anything else I can help you with?", reply_markup=reply_markup)

    context.user_data.clear()


if __name__ == "__main__":

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start_bot))
    app.add_handler(CallbackQueryHandler(confirm_transaction, pattern="confirm|cancel")) ## Prioritizing Callback Queries to confirm transactions
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
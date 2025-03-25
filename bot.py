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
        [InlineKeyboardButton("Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("Exit", callback_data="exit_bot")]
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
            last_transaction_response = (f"Your last transaction was of ${last_transaction["amount"]} at {last_transaction["time"]} , using {last_transaction["payment_method"]}."
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

            await query.message.reply_text("Enter the amount to be deposited(or Cancel to cancel the transaction):")
            context.user_data["action"] = "deposit"

        elif query.data == "withdraw":

            await query.message.reply_text("Enter the amount to be withdrawn(or Cancel to cancel the transaction):")
            context.user_data["action"] = "withdraw"

        ## Payment Method-related processes
        elif query.data == "add_payment_method":

            await add_payment_method(update, context)

        elif "new_method_" in query.data:

            await process_payment_method(update, context)

        elif "new_" not in query.data and "method_" in query.data:

            context.user_data["selected_payment_method"] = query.data.split("_")[-1]
            await confirm_transaction_prompt(update, context)

        elif "cancel" in query.data:

            await cancel_transaction(update, context)

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
            
            user_input = update.message.text.strip().lower()

            if user_input == "cancel":

                await cancel_transaction(update, context)
                return

            if "amount" not in context.user_data:

                amount = int(user_input)

                if amount <= 0:

                    await update.message.reply_text("The amount must be greater than zero. Please try again:")
                    return
                
                if action == "withdraw" and amount > user["balance"]:

                    await update.message.reply_text("Insufficient balance. Please try again:")
                    return

                context.user_data["amount"] = amount

            else:

                amount = context.user_data["amount"]

            context.user_data["original_action"] = action

            payment_methods = user.get("payment_methods", [])

            if payment_methods:

                keyboard_options = [
                    [InlineKeyboardButton(
                        "Paypal Account" if method['type'].lower() == "paypal" else 
                        method['details'] if isinstance(method['details'], str) else 
                        method['details']['currency'], 
                        callback_data=f"method_{method['type']}") for method in payment_methods]
                ]

            else:

                keyboard_options = []

            keyboard_options.append([InlineKeyboardButton("Add New Method", callback_data="add_payment_method")])
            keyboard_options.append([InlineKeyboardButton("Cancel", callback_data="cancel")])

            reply_markup = InlineKeyboardMarkup(keyboard_options)

            await update.message.reply_text(f"Select a method for your {action} of ${amount}:", reply_markup=reply_markup)

        except ValueError:

            await update.message.reply_text("Invalid number. Please try again:")

    elif action == "save_payment_method":

        if update.message.text.lower() == "cancel":

            await cancel_transaction(update, context)

        else:

            await save_payment_method(update, context)


async def confirm_transaction_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    action = context.user_data["action"]
    amount = context.user_data["amount"]

    keyboard_options = [
        [InlineKeyboardButton("Confirm", callback_data="confirm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard_options)


    if update.message:

        await update.message.reply_text(f"Confirm {action} of ${amount}?", reply_markup=reply_markup)

    elif update.callback_query:

        await update.callback_query.message.reply_text(f"Confirm {action} of ${amount}?", reply_markup=reply_markup)

    pass


async def confirm_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id
    action = context.user_data.get("action")
    amount = context.user_data.get("amount")
    selected_payment_method = context.user_data.get("selected_payment_method")


    user = users_collection.find_one({"user_id": user_id})
    new_balance = user["balance"] + amount if action == "deposit" else user["balance"] - amount

    users_collection.update_one({
        "user_id": user_id},
        {"$set": {
            "balance": new_balance,
            "last_transaction": {
                "amount": amount,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "payment_method": selected_payment_method
            }
        }}
    )
    
    await query.message.reply_text(f"{action.capitalize()} of ${amount}, utilizing {selected_payment_method['type']} was successful! Current Balance: ${new_balance}")

    await query.answer()

    keyboard_options = [
        [InlineKeyboardButton("Return to Main Menu", callback_data="return_main")],
        [InlineKeyboardButton("Exit", callback_data="exit_bot")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard_options)
    
    await query.message.reply_text("Is there anything else I can help you with?", reply_markup=reply_markup)

    context.user_data.clear()


async def add_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    query = update.callback_query

    keyboard_options = [
        [InlineKeyboardButton("Bank Transfer", callback_data="new_method_bank")],
        [InlineKeyboardButton("PayPal", callback_data="new_method_paypal")],
        [InlineKeyboardButton("Crypto", callback_data="new_method_crypto")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_options)

    await query.message.reply_text("Please select the payment method type you want to add, or press Cancel to cancel the operation:", reply_markup=reply_markup)


async def process_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    payment_method = query.data.split("_")[-1] ## With this, the possible payment methods fetched will be: bank, paypal and crypto.

    context.user_data["new_payment_method"] = payment_method ## Here, the new payment method type is saved to the user's data
    context.user_data["action"] = "save_payment_method" ## Here, the save_payment_method action is set, in order for the next function to run on the handle_message()

    if payment_method == "bank":

        await query.message.reply_text("Please enter the name of your bank (e.g., 'Chase') or type Cancel to exit:")

    elif payment_method == "paypal":

        await query.message.reply_text("Please enter your PayPal email address or type Cancel to exit:")

    elif payment_method == "crypto":

        await query.message.reply_text("Please choose a cryptocurrency (BTC, ETH, USDT) or type Cancel to exit:")

    await query.answer()

    if update.message and update.message.text.lower() == "cancel":

        await cancel_transaction(update, context)

async def save_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    payment_method = context.user_data.get("new_payment_method")
    details = update.message.text

    if payment_method == "crypto" and "new_payment_method_details" not in context.user_data:

        ## For Crypto, the crypto address will need to be included, after choosing the currency
        await update.message.reply_text("Please inform your crypto address:")
        context.user_data["new_payment_method_details"] = {"currency": details}

        return
    
    ## Saving the new payment method to the user's "account"

    user = users_collection.find_one({"user_id": user_id})

    if payment_method == "crypto" and "new_payment_method_details" in context.user_data:

        payment_method_details = context.user_data["new_payment_method_details"]
        payment_method_details["address"] = details
        new_payment_method = {"type": "Crypto", "details": payment_method_details}

    else:

        new_payment_method = {"type": payment_method.capitalize(), "details": details.capitalize()}

    ## Updating the user's payment methods
    users_collection.update_one({"user_id": user_id}, {"$push": {"payment_methods": new_payment_method}})

    await update.message.reply_text(f"{payment_method.capitalize()} payment method added successfully!")

    action = context.user_data.get("original_action")

    original_amount = context.user_data.get("amount")
    
    context.user_data.clear()

    context.user_data["amount"] = original_amount
    context.user_data["action"] = action
    context.user_data["selected_payment_method"] = new_payment_method

    await confirm_transaction_prompt(update, context)


async def cancel_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.callback_query:

        query = update.callback_query
        user_id = query.from_user.id

        await query.answer()
        await query.message.reply_text("The current transaction was canceled. Returning to the main menu...")

    else:

        user_id = update.message.from_user.id
        await update.message.reply_text("The current transaction was canceled. Returning to the main menu...")

    context.user_data.clear()
    await start_bot(update, context)


if __name__ == "__main__":

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start_bot))
    app.add_handler(CallbackQueryHandler(confirm_transaction, pattern="confirm"))
    app.add_handler(CallbackQueryHandler(cancel_transaction, pattern="cancel"))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
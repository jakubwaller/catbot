import asyncio
import datetime
import logging
import random

import pandas as pd
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from tools import run_request, read_config

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# httpx logs full request URLs at INFO, which would put the bot token in the logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

csv_file_name = "logs/cat_bot_logs.csv"
df_columns = ["group", "timestamp", "breed", "gif"]

config = read_config()
developer_chat_id = config["developer_chat_id"]
bot_token = config["bot_token"]
cat_api_key = config["cat_api_key"]
# TheCatAPI answers 403 without the key on /v1/breeds too, not only on image search
cat_api_headers = {"Content-Type": "application/json", "x-api-key": cat_api_key}

try:
    df = pd.read_csv(csv_file_name)
except Exception:
    df = pd.DataFrame(columns=df_columns)

# Loaded on first use, not at import: a failing breeds call must not keep the whole bot from starting
breeds_full = None


def get_breeds() -> list:
    global breeds_full
    if breeds_full is None:
        breeds = run_request("GET", "https://api.thecatapi.com/v1/breeds", request_headers=cat_api_headers)
        # Cache only a usable list, so an odd 200 answer is retried on the next call instead of kept until restart
        if not isinstance(breeds, list) or not breeds:
            raise Exception(f"Unexpected breeds response: {str(breeds)[:200]}")
        breeds_full = breeds
    return breeds_full


async def sendcatbybreed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with inline buttons attached."""
    breeds = await asyncio.to_thread(get_breeds)
    keyboard = [
        InlineKeyboardButton(breed["name"], callback_data=breed["name"] + "__" + breed["id"]) for breed in breeds
    ]

    chunk_size = 3
    chunks = [keyboard[x : x + chunk_size] for x in range(0, len(keyboard), chunk_size)]

    reply_markup = InlineKeyboardMarkup(chunks)
    logger.info("called breed")
    await update.message.reply_text("Please choose:", reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    await query.answer()

    breed_name = query.data.split("__")[0]
    breed_id = query.data.split("__")[1]
    await query.edit_message_text(text=f"Sending breed: {breed_name}")
    await send_cat_to_chat(query.message.chat, context, breed=breed_id)


async def hi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays info on how to use the bot."""
    await update.message.reply_text("Hi there! I'm a CatBot and can send images of cats.")


async def sendcatgif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a cat gif."""
    await send_cat_to_chat(update.message.chat, context, gif=True)


async def sendcat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a cat."""
    await send_cat_to_chat(update.message.chat, context)


async def send_cat_to_chat(chat: Chat, context: ContextTypes.DEFAULT_TYPE, breed=None, gif=False) -> None:
    """Sends a cat to the given chat."""

    if gif:
        extensions = ("gif",)
    elif breed:
        extensions = None
    else:
        extensions = ("jpg", "png")

    params = {"limit": 100}
    if breed:
        params["breed_ids"] = breed
    else:
        breed = "random"
    if extensions:
        params["mime_types"] = ",".join(extensions)

    logger.info(params)

    num_of_max_tries = 5
    num_of_tries = 1
    success = False

    while num_of_tries <= num_of_max_tries and not success:
        try:
            num_of_tries += 1

            response = await asyncio.to_thread(
                run_request,
                "GET",
                "https://api.thecatapi.com/v1/images/search",
                request_body=params,
                num_of_tries=5,
                request_headers=cat_api_headers,
            )
            # TheCatAPI ignores mime_types (about 5 gifs in 100 results either way), so the type is filtered here
            urls = [
                image["url"] for image in response if extensions is None or image["url"].lower().endswith(extensions)
            ]
            if not urls:
                raise Exception(f"No {params.get('mime_types')} image among {len(response)} results")
            url = random.choice(urls)

            if url.endswith(".gif"):
                await context.bot.send_animation(chat.id, url)
            else:
                await context.bot.send_photo(chat.id, url)

            success = True
        except Exception as e:
            if num_of_tries == num_of_max_tries:
                raise e
            else:
                logger.error(e)

    global df

    try:
        if "group" in chat.type:
            is_group = True
        else:
            is_group = False
    except Exception as e:
        logger.error(e)
        is_group = False

    df = pd.concat([df, pd.DataFrame([[is_group, datetime.datetime.now(), breed, gif]], columns=df_columns)])
    df.to_csv(csv_file_name, header=True, index=False)

    if is_group:
        is_group_text = "a group"
    else:
        is_group_text = "a single user"
    await context.bot.send_message(developer_chat_id, f"Sending a cat to {is_group_text}.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    await context.bot.send_message(chat_id=developer_chat_id, text=str(context.error))


def main() -> None:
    """Setup and run the bot."""
    application = Application.builder().token(bot_token).build()

    application.add_handler(CommandHandler("hi", hi))
    application.add_handler(CommandHandler("sendcat", sendcat))
    application.add_handler(CommandHandler("sendcatgif", sendcatgif))
    application.add_handler(CommandHandler("sendcatbybreed", sendcatbybreed))
    application.add_handler(CallbackQueryHandler(button))

    application.add_error_handler(error_handler)

    # Runs until the process receives SIGINT, SIGTERM or SIGABRT.
    application.run_polling(poll_interval=1)


if __name__ == "__main__":
    main()

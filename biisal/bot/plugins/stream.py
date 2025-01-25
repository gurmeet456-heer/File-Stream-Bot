import os
import asyncio
import requests
import string
import random
from asyncio import TimeoutError
from pyrogram import filters, Client
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from biisal.bot import StreamBot
from biisal.utils.database import Database
from biisal.utils.human_readable import humanbytes
from biisal.utils.file_properties import get_name, get_hash, get_media_file_size
from biisal.vars import Var
from urllib.parse import quote_plus

# Initialize the database
db = Database(Var.DATABASE_URL, Var.name)
pass_db = Database(Var.DATABASE_URL, "ag_passwords")

# Utility function to generate random alphanumeric strings
def generate_random_alphanumeric():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(8))

# Function to generate short links
def get_shortlink(url):
    try:
        response = requests.get(
            f"https://{Var.SHORTLINK_URL}/api",
            params={"api": Var.SHORTLINK_API, "url": url, "alias": generate_random_alphanumeric()}
        )
        data = response.json()
        if response.status_code == 200 and data.get("status") == "success":
            return data["shortenedUrl"]
        return url
    except Exception as e:
        print(f"Error in get_shortlink: {e}")
        return url

# Message template
msg_text = """
<b>Your link is generated... ⚡</b>

<b>📧 File Name: </b> <i>{}</i>
<b>📦 File Size: </b> <i>{}</i>

<b>⚠️ This link will expire after 6 hours.</b>

<b>❇️ By: @TechifyBots</b>
"""

@StreamBot.on_message(
    filters.private & (filters.document | filters.video | filters.audio | filters.photo),
    group=4
)
async def private_receive_handler(client: Client, message: Message):
    try:
        # Add user to the database if they don't exist
        if not await db.is_user_exist(message.from_user.id):
            await db.add_user(message.from_user.id)
            await client.send_message(
                Var.NEW_USER_LOG,
                f"#NewUser\n\n**Name - [{message.from_user.first_name}](tg://user?id={message.from_user.id})**"
            )

        # Check if the user is subscribed to the updates channel
        if Var.UPDATES_CHANNEL != "None":
            try:
                user_status = await client.get_chat_member(Var.UPDATES_CHANNEL, message.from_user.id)
                if user_status.status == "kicked":
                    await message.reply_text(
                        "You are banned! Contact [Support](https://telegram.me/CallOwnerBot).",
                        disable_web_page_preview=True
                    )
                    return
            except UserNotParticipant:
                await message.reply_photo(
                    photo="https://graph.org/file/a8095ab3c9202607e78ad.jpg",
                    caption="<b>Join our updates channel to use me.</b>",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Join Now 🚩", url=f"https://telegram.me/{Var.UPDATES_CHANNEL}")]]
                    )
                )
                return
            except Exception as e:
                await message.reply_text(
                    f"An error occurred: {e}",
                    disable_web_page_preview=True
                )
                return

        # Check if the user is banned
        if await db.is_banned(message.from_user.id):
            await message.reply_text(Var.BAN_ALERT)
            return

        # Process the message
        log_msg = await message.copy(chat_id=Var.BIN_CHANNEL)
        stream_link = f"{Var.URL}watch/{log_msg.id}/{quote_plus(get_name(log_msg))}?hash={get_hash(log_msg)}"
        download_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(log_msg))}?hash={get_hash(log_msg)}"

        # Shorten links if enabled
        if Var.SHORTLINK:
            stream_link = get_shortlink(stream_link)
            download_link = get_shortlink(download_link)

        # Send links to the user
        await message.reply_text(
            text=msg_text.format(get_name(log_msg), humanbytes(get_media_file_size(message))),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("• Stream •", url=stream_link),
                    InlineKeyboardButton("• Download •", url=download_link)
                ],
                [
                    InlineKeyboardButton(
                        "🧿 Watch on Telegram 🖥", web_app=WebAppInfo(url=stream_link)
                    )
                ]
            ])
        )

        # Schedule deletion after 6 hours
        await asyncio.sleep(21600)
        await log_msg.delete()

    except FloodWait as e:
        print(f"FloodWait: Sleeping for {e.x} seconds.")
        await asyncio.sleep(e.x)
    except Exception as e:
        print(f"Error: {e}")

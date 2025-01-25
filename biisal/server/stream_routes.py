import re
import time
import math
import logging
import secrets
import mimetypes
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from biisal.bot import multi_clients, work_loads, StreamBot
from biisal.server.exceptions import FIleNotFound, InvalidHash
from biisal import StartTime, __version__
from ..utils.time_format import get_readable_time
from ..utils.custom_dl import ByteStreamer
from biisal.utils.render_template import render_page
from biisal.vars import Var

routes = web.RouteTableDef()

# Root Route for Server Status
@routes.get("/", allow_head=True)
async def root_route_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + StreamBot.username,
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": __version__,
        }
    )

# Watch Route: Serve Custom HTML Streaming Page
@routes.get(r"/watch/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")

        # Generate file URL for streaming
        file_url = f"/{path}"  # File URL pointing to the streaming route
        file_name = f"File-{id}"  # Dummy file name for display

        # Custom HTML template
        html_template = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{file_name}</title>
            <link rel="stylesheet" href="https://unpkg.com/sheryjs/dist/Shery.css" />
            <link rel="stylesheet" href="https://aeditx03.github.io/resources/StreamCSS.css">
            <link rel="stylesheet" href="https://aeditx03.github.io/resources/playerCss.css">
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body>
            <center>
                <div class="main">
                    <video id="player" class="player" src="{file_url}" type="video/mp4" playsinline controls width="100%"></video>
                    <div class="file-name">
                        <h4>File name:</h4>
                        <p>{file_name}</p>
                    </div>
                </div>
            </center>
        </body>
        </html>
        """
        return web.Response(text=html_template, content_type="text/html")
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

# Streaming Route: Serve Files as Streams
@routes.get(r"/{path:\S+}", allow_head=True)
async def media_streamer(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")

        # Get the file properties
        range_header = request.headers.get("Range", 0)
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]

        tg_connect = ByteStreamer(faster_client)
        file_id = await tg_connect.get_file_properties(id)

        if file_id.unique_id[:6] != secure_hash:
            raise InvalidHash

        file_size = file_id.file_size

        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
        else:
            from_bytes = 0
            until_bytes = file_size - 1

        req_length = until_bytes - from_bytes + 1

        return web.Response(
            status=206 if range_header else 200,
            body=tg_connect.yield_file(file_id, 0, from_bytes, until_bytes),
            headers={
                "Content-Type": file_id.mime_type or "application/octet-stream",
                "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                "Content-Length": str(req_length),
                "Accept-Ranges": "bytes",
            },
        )
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

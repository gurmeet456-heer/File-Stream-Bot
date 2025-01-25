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
from biisal import StartTime, version
from ..utils.time_format import get_readable_time
from ..utils.custom_dl import ByteStreamer
from biisal.utils.render_template import render_page
from biisal.vars import Var

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(_):
    """
    Root route handler to provide server status information.
    """
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
            "version": version,
        }
    )

@routes.get(r"/watch/{path:\S+}", allow_head=True)
async def stream_handler_html(request: web.Request):
    """
    Stream handler for rendering HTML pages.
    """
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return web.Response(text=await render_page(id, secure_hash), content_type='text/html')
    except InvalidHash as e:
        logging.warning(f"Invalid hash error: {e}")
        raise web.HTTPForbidden(text="Invalid hash provided.")
    except FIleNotFound as e:
        logging.warning(f"File not found: {e}")
        raise web.HTTPNotFound(text="File not found.")
    except Exception as e:
        logging.critical(f"Unhandled error: {e}")
        raise web.HTTPInternalServerError(text="An internal server error occurred.")

@routes.get(r"/media/{path:\S+}", allow_head=True)
async def stream_handler_media(request: web.Request):
    """
    Stream handler for media files.
    """
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return await media_streamer(request, id, secure_hash)
    except InvalidHash as e:
        logging.warning(f"Invalid hash error: {e}")
        raise web.HTTPForbidden(text="Invalid hash provided.")
    except FIleNotFound as e:
        logging.warning(f"File not found: {e}")
        raise web.HTTPNotFound(text="File not found.")
    except Exception as e:
        logging.critical(f"Unhandled error: {e}")
        raise web.HTTPInternalServerError(text="An internal server error occurred.")

class_cache = {}

async def media_streamer(request: web.Request, id: int, secure_hash: str):
    """
    Stream media files with support for range requests.
    """
    range_header = request.headers.get("Range")
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if Var.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    
    logging.debug("Fetching file properties.")
    file_id = await tg_connect.get_file_properties(id)
    
    if file_id.unique_id[:6] != secure_hash:
        logging.warning(f"Invalid hash for message with ID {id}")
        raise InvalidHash

    file_size = file_id.file_size

    from_bytes, until_bytes = 0, file_size - 1
    if range_header:
        try:
            from_bytes, until_bytes = map(
                lambda x: int(x) if x else None,
                range_header.replace("bytes=", "").split("-")
            )
            until_bytes = until_bytes or file_size - 1
        except (ValueError, TypeError):
            logging.warning("Invalid Range header.")
            raise web.HTTPBadRequest(text="Invalid Range header.")

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            text="416: Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    chunk_size = 1024 * 1024
    body = tg_connect.yield_file(
        file_id, index, from_bytes, until_bytes, chunk_size
    )

    mime_type = file_id.mime_type or "application/octet-stream"
    file_name = file_id.file_name or f"{secrets.token_hex(2)}.unknown"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(until_bytes - from_bytes + 1),
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )

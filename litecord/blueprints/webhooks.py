"""

Litecord
Copyright (C) 2018-2021  Luna Mendes and Litecord Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

import secrets
import hashlib
from typing import Dict, Any, Optional, TYPE_CHECKING

import asyncpg
from quart import Blueprint, jsonify

from litecord.auth import token_check
from litecord.blueprints.checks import (
    channel_check,
    channel_perm_check,
    guild_check,
    guild_perm_check,
)
from litecord.blueprints.channel.messages import _spawn_embed, _del_msg_fkeys
from ..common.interop import message_view

from litecord.schemas import (
    validate,
    WEBHOOK_CREATE,
    WEBHOOK_UPDATE,
    WEBHOOK_MESSAGE_CREATE,
    WEBHOOK_MESSAGE_UPDATE,
)
from litecord.enums import WebhookType

from litecord.utils import async_map, str_bool, to_update
from litecord.errors import MissingAccess, NotFound

from litecord.common.messages import (
    msg_create_request,
    msg_create_check_content,
    msg_add_attachment,
    msg_guild_text_mentions,
)
from litecord.embed.sanitizer import fill_embed, fetch_mediaproxy_img
from litecord.embed.messages import process_url_embed, is_media_url
from litecord.embed.schemas import EmbedURL
from litecord.json import pg_set_json
from litecord.enums import MessageType
from litecord.images import STATIC_IMAGE_MIMES

if TYPE_CHECKING:
    from litecord.typing_hax import app, request
else:
    from quart import current_app as app, request

bp = Blueprint("webhooks", __name__)


async def get_webhook(webhook_id: int, *, secure: bool = True) -> Optional[Dict[str, Any]]:
    """Get a webhook data"""
    row = await app.db.fetchrow(
        """
    SELECT id::text, guild_id::text, channel_id::text, creator_id,
           name, avatar, token, type, source_id
    FROM webhooks
    WHERE id = $1
    """,
        webhook_id,
    )

    if not row:
        return None

    drow = dict(row)

    type = drow["type"]
    if type != WebhookType.INCOMING.value:
        drow.pop("token")

    # Get partial source data
    source_id = drow.pop("source_id", None)
    if source_id:
        source_guild_id = await app.storage.guild_from_channel(source_id)

        row = await app.db.fetchrow(
            """SELECT id::text, name
        FROM guild_channels
        WHERE id = $1
        """,
            source_id,
        )
        drow["source_channel"] = dict(row) if row else None

        row = await app.db.fetchrow(
            """SELECT id::text, name, icon
        FROM guilds
        WHERE id = $1
        """,
            source_guild_id,
        )
        drow["source_guild"] = dict(row) if row else None

    drow["user"] = await app.storage.get_user(drow.pop("creator_id"))
    drow["application_id"] = None

    if not secure:
        drow.pop("user")

    return drow


async def _webhook_check(channel_id):
    user_id = await token_check()

    await channel_check(user_id, channel_id)
    await channel_perm_check(user_id, channel_id, "manage_webhooks")

    return user_id


async def _webhook_check_guild(guild_id):
    user_id = await token_check()

    await guild_check(user_id, guild_id)
    await guild_perm_check(user_id, guild_id, "manage_webhooks")

    return user_id


async def _webhook_check_fw(webhook_id):
    """Make a check from an incoming webhook id (fw = from webhook)."""
    await token_check()

    guild_id = await app.db.fetchval(
        """
    SELECT guild_id FROM webhooks
    WHERE id = $1
    """,
        webhook_id,
    )

    if guild_id is None:
        raise MissingAccess()

    return (await _webhook_check_guild(guild_id)), guild_id


async def _webhook_many(where_clause, arg: int):
    webhook_ids = await app.db.fetch(
        f"""
    SELECT id
    FROM webhooks
    {where_clause}
    """,
        arg,
    )

    webhook_ids = [r["id"] for r in webhook_ids]

    return jsonify(await async_map(get_webhook, webhook_ids))


async def webhook_token_check(webhook_id: int, webhook_token: str):
    """token_check() equivalent for webhooks."""
    row = await app.db.fetchrow(
        """
    SELECT guild_id, channel_id
    FROM webhooks
    WHERE id = $1 AND token = $2
    """,
        webhook_id,
        webhook_token,
    )

    if row is None:
        raise NotFound(10015)

    return row["guild_id"], row["channel_id"]


async def _dispatch_webhook_update(guild_id: int, channel_id):
    await app.dispatcher.guild.dispatch(
        guild_id,
        (
            "WEBHOOKS_UPDATE",
            {"guild_id": str(guild_id), "channel_id": str(channel_id)},
        ),
    )


@bp.route("/channels/<int:channel_id>/webhooks", methods=["POST"])
async def create_webhook(channel_id: int):
    """Create a webhook given a channel."""
    user_id = await _webhook_check(channel_id)

    j = validate(await request.get_json(), WEBHOOK_CREATE)

    guild_id = await app.storage.guild_from_channel(channel_id)

    webhook_id = app.winter_factory.snowflake()

    token = secrets.token_urlsafe(40)

    webhook_icon = await app.icons.put(
        "user_avatar",
        webhook_id,
        j.get("avatar") or None,
        always_icon=True,
        size=(1024, 1024),
    )

    await app.db.execute(
        """
        INSERT INTO webhooks
            (id, guild_id, channel_id, creator_id, name, avatar, token)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7)
        """,
        webhook_id,
        guild_id,
        channel_id,
        user_id,
        j["name"],
        webhook_icon.icon_hash,
        token,
    )

    await _dispatch_webhook_update(guild_id, channel_id)
    return jsonify(await get_webhook(webhook_id))


@bp.route("/channels/<int:channel_id>/webhooks", methods=["GET"])
async def get_channel_webhook(channel_id: int):
    """Get a list of webhooks in a channel"""
    await _webhook_check(channel_id)
    return await _webhook_many("WHERE channel_id = $1", channel_id)


@bp.route("/guilds/<int:guild_id>/webhooks", methods=["GET"])
async def get_guild_webhook(guild_id):
    """Get all webhooks in a guild"""
    await _webhook_check_guild(guild_id)
    return await _webhook_many("WHERE guild_id = $1", guild_id)


@bp.route("/webhooks/<int:webhook_id>", methods=["GET"])
async def get_single_webhook(webhook_id):
    """Get a single webhook's information."""
    await _webhook_check_fw(webhook_id)
    return jsonify(await get_webhook(webhook_id))


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>", methods=["GET"])
async def get_tokened_webhook(webhook_id, webhook_token):
    """Get a webhook using its token."""
    await webhook_token_check(webhook_id, webhook_token)
    return jsonify(await get_webhook(webhook_id, secure=False))


async def _update_webhook(webhook_id: int, j: dict):
    if "name" in j:
        await app.db.execute(
            """
        UPDATE webhooks
        SET name = $1
        WHERE id = $2
        """,
            j["name"],
            webhook_id,
        )

    if "channel_id" in j:
        await app.db.execute(
            """
        UPDATE webhooks
        SET channel_id = $1
        WHERE id = $2
        """,
            j["channel_id"],
            webhook_id,
        )

    if "avatar" in j:
        new_icon = await app.icons.update(
            "user_avatar",
            webhook_id,
            j["avatar"] or None,
            always_icon=True,
            size=(1024, 1024),
        )

        await app.db.execute(
            """
        UPDATE webhooks
        SET icon = $1
        WHERE id = $2
        """,
            new_icon.icon_hash,
            webhook_id,
        )


@bp.route("/webhooks/<int:webhook_id>", methods=["PATCH"])
async def modify_webhook(webhook_id: int):
    """Patch a webhook."""
    _user_id, guild_id = await _webhook_check_fw(webhook_id)
    j = validate(await request.get_json(), WEBHOOK_UPDATE)

    if "channel_id" in j:
        chan = await app.storage.get_channel(j["channel_id"])
        if (j["channel_id"] and not chan) or (chan and chan["guild_id"] != str(guild_id)):
            raise NotFound(10003)

    await _update_webhook(webhook_id, j)

    webhook = await get_webhook(webhook_id)
    assert webhook is not None

    # we don't need to cast channel_id to int since that isn't
    # used in the dispatcher call
    await _dispatch_webhook_update(guild_id, webhook["channel_id"])
    return jsonify(webhook)


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>", methods=["PATCH"])
async def modify_webhook_tokened(webhook_id, webhook_token):
    """Modify a webhook, using its token."""
    guild_id, channel_id = await webhook_token_check(webhook_id, webhook_token)

    # forcefully pop() the channel id out of the schema
    # instead of making another, for simplicity's sake
    j = await request.get_json()
    j.pop("channel_id", None)
    j = validate(j, WEBHOOK_UPDATE)

    await _update_webhook(webhook_id, j)
    await _dispatch_webhook_update(guild_id, channel_id)
    return jsonify(await get_webhook(webhook_id, secure=False))


async def delete_webhook(webhook_id: int):
    """Delete a webhook."""
    webhook = await get_webhook(webhook_id)
    assert webhook is not None

    # TODO use returning?
    res = await app.db.execute(
        """
    DELETE FROM webhooks
    WHERE id = $1
    """,
        webhook_id,
    )

    if res.lower() == "delete 0":
        raise NotFound(10015)

    # only casting the guild id since that's whats used
    # on the dispatcher call.
    await _dispatch_webhook_update(int(webhook["guild_id"]), webhook["channel_id"])


@bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
async def del_webhook(webhook_id):
    """Delete a webhook."""
    await _webhook_check_fw(webhook_id)
    await delete_webhook(webhook_id)
    return "", 204


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>", methods=["DELETE"])
async def del_webhook_tokened(webhook_id, webhook_token):
    """Delete a webhook, with its token."""
    await webhook_token_check(webhook_id, webhook_token)
    await delete_webhook(webhook_id)
    return "", 204


async def create_message_webhook(guild_id, channel_id, webhook_id, data):
    """Create a message, but for webhooks only."""
    message_id = app.winter_factory.snowflake()

    async with app.db.acquire() as conn:
        await pg_set_json(conn)

        await conn.execute(
            """
            INSERT INTO messages (id, channel_id, guild_id,
                content, tts, mention_everyone, message_type, embeds)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            message_id,
            channel_id,
            guild_id,
            data["content"],
            data["tts"],
            data["everyone_mention"],
            MessageType.DEFAULT.value,
            data.get("embeds", []),
        )

        info = data["info"]

        await conn.execute(
            """
        INSERT INTO message_webhook_info
            (message_id, webhook_id, name, avatar)
        VALUES
            ($1, $2, $3, $4)
        """,
            message_id,
            webhook_id,
            info["name"],
            info["avatar"],
        )

    return message_id


async def _webhook_avy_redir(webhook_id: int, avatar_url: EmbedURL):
    """Create a row on webhook_avatars."""
    url_hash = hashlib.sha256(avatar_url.to_md_path.encode()).hexdigest()

    try:
        await app.db.execute(
            """
        INSERT INTO webhook_avatars (webhook_id, hash, md_url_redir)
        VALUES ($1, $2, $3)
        """,
            webhook_id,
            url_hash,
            avatar_url.url,
        )
    except asyncpg.UniqueViolationError:
        pass

    return url_hash


async def _create_avatar(webhook_id: int, avatar_url: EmbedURL) -> Optional[str]:
    """Create an avatar for a webhook out of an avatar URL,
    given when executing the webhook.

    Litecord will write an URL that redirects to the given avatar_url,
    using mediaproxy.
    """
    if avatar_url.scheme not in ("http", "https"):
        return None

    if not is_media_url(avatar_url):
        return None

    # we still fetch the URL to check its validity, mimetypes, etc
    # but in the end, we will store it under the webhook_avatars table,
    # not IconManager.
    res = await fetch_mediaproxy_img(avatar_url)
    if res is None:
        return None
    resp, raw = res
    # raw_b64 = base64.b64encode(raw).decode()

    mime = resp.headers["content-type"]

    # TODO: apng checks are missing (for this and everywhere else)
    if mime not in STATIC_IMAGE_MIMES:
        return None

    return await _webhook_avy_redir(webhook_id, avatar_url)


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>", methods=["POST"])
async def execute_webhook(webhook_id: int, webhook_token):
    """Execute a webhook. Sends a message to the channel the webhook
    is tied to."""
    guild_id, channel_id = await webhook_token_check(webhook_id, webhook_token)

    # TODO: ensure channel_id points to guild text channel

    payload_json, files = await msg_create_request()

    # NOTE: we really pop here instead of adding a kwarg
    # to msg_create_request just because of webhooks.
    # nonce isn't allowed on WEBHOOK_MESSAGE_CREATE
    payload_json.pop("nonce")

    j = validate(payload_json, WEBHOOK_MESSAGE_CREATE)

    msg_create_check_content(j, files)
    wait = request.args.get("wait", type=str_bool)

    # webhooks don't need permissions.
    mentions_everyone = "@everyone" in j["content"]
    mentions_here = "@here" in j["content"]

    webhook = await get_webhook(webhook_id)
    assert webhook is not None

    # webhooks have TWO avatars. one is from settings, the other is from
    # the json's icon_url. one can be handled gracefully by IconManager,
    # but the other can't, at all.
    avatar = webhook["avatar"]

    if "avatar_url" in j and j["avatar_url"] is not None:
        parsed = await _create_avatar(webhook_id, j["avatar_url"])
        if parsed:
            avatar = parsed

    message_id = await create_message_webhook(
        guild_id,
        channel_id,
        webhook_id,
        {
            "content": j.get("content", ""),
            "tts": j.get("tts", False),
            "everyone_mention": mentions_everyone or mentions_here,
            "embeds": [
                await fill_embed(embed)
                for embed in ((j.get("embeds") or []) or [j["embed"]] if "embed" in j and j["embed"] else [])
            ],
            "info": {"name": j.get("username", webhook["name"]), "avatar": avatar},
        },
    )

    for pre_attachment in files:
        await msg_add_attachment(message_id, channel_id, None, pre_attachment)

    payload = await app.storage.get_message(message_id, include_member=True)

    await app.dispatcher.channel.dispatch(channel_id, ("MESSAGE_CREATE", payload))

    # spawn embedder in the background, even when we're on a webhook.
    app.sched.spawn(process_url_embed(payload))

    # we can assume its a guild text channel, so just call it
    await msg_guild_text_mentions(payload, guild_id, mentions_everyone, mentions_here)

    if wait:
        return jsonify(message_view(payload))
    return "", 204


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>/slack", methods=["POST"])
async def execute_slack_webhook(webhook_id, webhook_token):
    """Execute a webhook but expecting Slack data."""
    # TODO: know slack webhooks
    await webhook_token_check(webhook_id, webhook_token)
    return "", 204


@bp.route("/webhooks/<int:webhook_id>/<webhook_token>/github", methods=["POST"])
async def execute_github_webhook(webhook_id, webhook_token):
    """Execute a webhook but expecting GitHub data."""
    # TODO: know github webhooks
    await webhook_token_check(webhook_id, webhook_token)
    return "", 204


@bp.route(
    "/webhooks/<int:webhook_id>/<webhook_token>/messages/<int:message_id>",
    methods=["GET"],
)
async def get_webhook_message(webhook_id, webhook_token, message_id):
    """Get a message from a webhook."""
    await webhook_token_check(webhook_id, webhook_token)

    payload = await app.storage.get_message(message_id)
    if not payload or not payload["webhook_id"] or int(payload["webhook_id"]) != webhook_id:
        raise NotFound(10008)

    return jsonify(message_view(payload))


@bp.route(
    "/webhooks/<int:webhook_id>/<webhook_token>/messages/<int:message_id>",
    methods=["PATCH"],
)
async def update_webhook_message(webhook_id, webhook_token, message_id):
    """Update a message from a webhook."""
    _, channel_id = await webhook_token_check(webhook_id, webhook_token)

    old_message = await app.storage.get_message(message_id)
    if not old_message or not old_message["webhook_id"] or int(old_message["webhook_id"]) != webhook_id:
        raise NotFound(10008)

    j = validate(await request.get_json(), WEBHOOK_MESSAGE_UPDATE)
    updated = False
    embeds = None

    if to_update(j, old_message, "content"):
        updated = True
        await app.db.execute(
            """
        UPDATE messages
        SET content=$1
        WHERE messages.id = $2
        """,
            j["content"] or "",
            message_id,
        )

    if "embed" in j or "embeds" in j:
        updated = True
        embeds = [
            await fill_embed(embed)
            for embed in ((j.get("embeds") or []) or [j["embed"]] if "embed" in j and j["embed"] else [])
        ]
        await app.db.execute(
            """
        UPDATE messages
        SET embeds=$1
        WHERE messages.id = $2
        """,
            embeds,
            message_id,
        )

        # the artificial delay keeps consistency between the events, since
        # it makes more sense for the MESSAGE_UPDATE with new content to come
        # BEFORE the MESSAGE_UPDATE with the new embeds (based on content)
        await _spawn_embed(
            {
                "id": message_id,
                "channel_id": channel_id,
                "content": j["content"],
                "embeds": old_message["embeds"],
            },
            delay=0.2,
        )

    # only set new timestamp upon actual update
    if updated:
        await app.db.execute(
            """
        UPDATE messages
        SET edited_at = (now() at time zone 'utc')
        WHERE id = $1
        """,
            message_id,
        )

    message = await app.storage.get_message(message_id, user_id)

    # only dispatch MESSAGE_UPDATE if any update
    # actually happened
    if updated:
        await app.dispatcher.channel.dispatch(channel_id, ("MESSAGE_UPDATE", message))

    return jsonify(message_view(message))


@bp.route(
    "/webhooks/<int:webhook_id>/<webhook_token>/messages/<int:message_id>",
    methods=["DELETE"],
)
async def delete_webhook_message(webhook_id, webhook_token, message_id):
    """Delete a message from a webhook."""
    guild_id, channel_id = await webhook_token_check(webhook_id, webhook_token)

    payload = await app.storage.get_message(message_id)
    if not payload or not payload["webhook_id"] or int(payload["webhook_id"]) != webhook_id:
        raise NotFound(10008)

    await _del_msg_fkeys(message_id, channel_id)
    await app.db.execute(
        """
    DELETE FROM messages
    WHERE messages.id = $1
    """,
        message_id,
    )

    await app.dispatcher.channel.dispatch(
        channel_id,
        (
            "MESSAGE_DELETE",
            {
                "id": str(message_id),
                "channel_id": str(channel_id),
                "guild_id": str(guild_id),
            },
        ),
    )

    return "", 204

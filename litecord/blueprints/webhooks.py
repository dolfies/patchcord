"""

Litecord
Copyright (C) 2018-2019  Luna Mendes

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
from typing import Dict, Any, Optional

from quart import Blueprint, jsonify, current_app as app, request

from litecord.auth import token_check
from litecord.blueprints.checks import (
    channel_check, channel_perm_check, guild_check, guild_perm_check
)

from litecord.schemas import validate, WEBHOOK_CREATE, WEBHOOK_UPDATE
from litecord.enums import ChannelType
from litecord.snowflake import get_snowflake
from litecord.utils import async_map
from litecord.errors import WebhookNotFound, Unauthorized

bp = Blueprint('webhooks', __name__)


async def get_webhook(webhook_id: int, *,
                      secure: bool=True) -> Optional[Dict[str, Any]]:
    """Get a webhook data"""
    row = await app.db.fetchrow("""
    SELECT id::text, guild_id::text, channel_id::text, creator_id
           name, avatar, token
    FROM webhooks
    WHERE id = $1
    """, webhook_id)

    if not row:
        return None

    drow = dict(row)

    drow['user'] = await app.storage.get_user(row['creator_id'])
    drow.pop('creator_id')

    if not secure:
        drow.pop('user')
        drow.pop('guild_id')

    return drow


async def _webhook_check(channel_id):
    user_id = await token_check()

    await channel_check(user_id, channel_id, ChannelType.GUILD_TEXT)
    await channel_perm_check(user_id, channel_id, 'manage_webhooks')

    return user_id


async def _webhook_check_guild(guild_id):
    user_id = await token_check()

    await guild_check(user_id, guild_id)
    await guild_perm_check(user_id, guild_id, 'manage_webhooks')

    return user_id


async def _webhook_check_fw(webhook_id):
    """Make a check from an incoming webhook id (fw = from webhook)."""
    guild_id = await app.db.fetchval("""
    SELECT guild_id FROM webhooks
    WHERE id = $1
    """, webhook_id)

    if guild_id is None:
        raise WebhookNotFound()

    return await _webhook_check_guild(guild_id)


async def _webhook_many(where_clause, arg: int):
    webhook_ids = await app.db.fetch(f"""
    SELECT id
    FROM webhooks
    {where_clause}
    """, arg)

    webhook_ids = [r['id'] for r in webhook_ids]

    return jsonify(
        await async_map(get_webhook, webhook_ids)
    )


async def webhook_token_check(webhook_id: int, webhook_token: str):
    """token_check() equivalent for webhooks."""
    webhook_id_fetch = await app.db.fetchrow("""
    SELECT id
    FROM webhooks
    WHERE id = $1 AND token = $2
    """, webhook_id, webhook_token)

    if webhook_id_fetch is None:
        raise Unauthorized('webhook not found or unauthorized')


@bp.route('/channels/<int:channel_id>/webhooks', methods=['POST'])
async def create_webhook(channel_id: int):
    """Create a webhook given a channel."""
    user_id = await _webhook_check(channel_id)

    j = validate(await request.get_json(), WEBHOOK_CREATE)

    guild_id = await app.storage.guild_from_channel(channel_id)

    webhook_id = get_snowflake()

    # I'd say generating a full fledged token with itsdangerous is
    # relatively wasteful since webhooks don't even have a password_hash,
    # and we don't make a webhook in the users table either.
    token = secrets.token_urlsafe(40)

    webhook_icon = await app.icons.put(
        'user', webhook_id, j.get('avatar'),
        always_icon=True, size=(128, 128)
    )

    await app.db.execute(
        """
        INSERT INTO webhooks
            (id, guild_id, channel_id, creator_id, name, avatar, token)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7)
        """,
        webhook_id, guild_id, channel_id, user_id,
        j['name'], webhook_icon.icon_hash, token
    )

    return jsonify(await get_webhook(webhook_id))


@bp.route('/channels/<int:channel_id>/webhooks', methods=['GET'])
async def get_channel_webhook(channel_id: int):
    """Get a list of webhooks in a channel"""
    await _webhook_check(channel_id)
    return await _webhook_many('WHERE channel_id = $1', channel_id)


@bp.route('/guilds/<int:guild_id>/webhooks', methods=['GET'])
async def get_guild_webhook(guild_id):
    """Get all webhooks in a guild"""
    await _webhook_check_guild(guild_id)
    return await _webhook_many('WHERE guild_id = $1', guild_id)


@bp.route('/webhooks/<int:webhook_id>', methods=['GET'])
async def get_single_webhook(webhook_id):
    """Get a single webhook's information."""
    await _webhook_check_fw(webhook_id)
    return await jsonify(await get_webhook(webhook_id))


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>', methods=['GET'])
async def get_tokened_webhook(webhook_id, webhook_token):
    """Get a webhook using its token."""
    await webhook_token_check(webhook_id, webhook_token)
    return await jsonify(await get_webhook(webhook_id, secure=False))


async def _update_webhook(webhook_id: int, j: dict):
    if 'name' in j:
        await app.db.execute("""
        UPDATE webhooks
        SET name = $1
        WHERE id = $2
        """, j['name'], webhook_id)

    if 'channel_id' in j:
        await app.db.execute("""
        UPDATE webhooks
        SET channel_id = $1
        WHERE id = $2
        """, j['name'], webhook_id)

    if 'avatar' in j:
        new_icon = await app.icons.update(
            'user', webhook_id, j['avatar'], always_icon=True, size=(128, 128)
        )

        await app.db.execute("""
        UPDATE webhooks
        SET icon = $1
        WHERE id = $2
        """, new_icon.icon_hash, webhook_id)


@bp.route('/webhooks/<int:webhook_id>', methods=['PATCH'])
async def modify_webhook(webhook_id: int):
    """Patch a webhook."""
    await _webhook_check_fw(webhook_id)
    j = validate(await request.get_json(), WEBHOOK_UPDATE)

    await _update_webhook(webhook_id, j)
    return jsonify(await get_webhook(webhook_id))


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>', methods=['PATCH'])
async def modify_webhook_tokened(webhook_id, webhook_token):
    """Modify a webhook, using its token."""
    await webhook_token_check(webhook_id, webhook_token)

    # forcefully pop() the channel id out of the schema
    # instead of making another, for simplicity's sake
    j = validate(await request.get_json(),
                 WEBHOOK_UPDATE.pop('channel_id'))

    await _update_webhook(webhook_id, j)
    return jsonify(await get_webhook(webhook_id, secure=False))


@bp.route('/webhooks/<int:webhook_id>', methods=['DELETE'])
async def del_webhook(webhook_id):
    pass


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>', methods=['DELETE'])
async def del_webhook_tokened(webhook_id, webhook_token):
    pass


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>', methods=['POST'])
async def execute_webhook(webhook_id, webhook_token):
    pass


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>/slack',
          methods=['POST'])
async def execute_slack_webhook(webhook_id, webhook_token):
    pass


@bp.route('/webhooks/<int:webhook_id>/<webhook_token>/github', methods=['POST'])
async def execute_github_webhook(webhook_id, webhook_token):
    pass

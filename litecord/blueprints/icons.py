from os.path import splitext
from quart import Blueprint, current_app as app, send_file

bp = Blueprint('images', __name__)


async def send_icon(scope, key, icon_hash, **kwargs):
    """Send an icon."""
    icon = await app.icons.generic_get(
        scope, key, icon_hash, **kwargs)

    if not icon:
        return '', 404

    return await send_file(icon.as_path)


def splitext_(filepath):
    name, ext = splitext(filepath)
    return name, ext.strip('.')


@bp.route('/emojis/<int:emoji_id>.<ext>', methods=['GET'])
async def _get_raw_emoji(emoji_id: int, ext: str):
    # emoji = app.icons.get_emoji(emoji_id, ext=ext)
    # just a test file for now
    return await send_file('./LICENSE')


@bp.route('/icons/<int:guild_id>/<icon_file>', methods=['GET'])
async def _get_guild_icon(guild_id: int, icon_file: str):
    icon_hash, ext = splitext_(icon_file)
    return await send_icon('guild', guild_id, icon_hash, ext=ext)


@bp.route('/splashes/<int:guild_id>/<icon_hash>.<ext>', methods=['GET'])
async def _get_guild_splash(guild_id: int, splash_hash: str, ext: str):
    pass


@bp.route('/embed/avatars/<int:discrim>.png')
async def _get_default_user_avatar(discrim: int):
    pass


@bp.route('/avatars/<int:user_id>/<avatar_hash>.<ext>')
async def _get_user_avatar(user_id, avatar_hash, ext):
    return await send_icon('user', user_id, avatar_hash, ext=ext)


# @bp.route('/app-icons/<int:application_id>/<icon_hash>.<ext>')
async def get_app_icon(application_id, icon_hash, ext):
    pass

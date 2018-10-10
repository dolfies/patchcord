from quart import Blueprint, jsonify, request, current_app as app
from asyncpg import UniqueViolationError

from ..auth import token_check
from ..schemas import validate, RELATIONSHIP, SPECIFIC_FRIEND
from ..enums import RelationshipType


bp = Blueprint('relationship', __name__)


@bp.route('/@me/relationships', methods=['GET'])
async def get_me_relationships():
    user_id = await token_check()
    return jsonify(await app.storage.get_relationships(user_id))


async def make_friend(user_id: int, peer_id: int,
                      rel_type=RelationshipType.FRIEND.value):
    _friend = RelationshipType.FRIEND.value

    await app.db.execute("""
    INSERT INTO relationships (user_id, peer_id, rel_type)
    VALUES ($1, $2, $3)
    """, user_id, peer_id, rel_type)

    # check if this is an acceptance
    # of a friend request
    existing = await app.db.fetchrow("""
    SELECT user_id, peer_id
    FROM relationships
    WHERE user_id = $1 AND peer_id = $2 AND rel_type = $3
    """, peer_id, user_id, _friend)

    _dispatch = app.dispatcher.dispatch_user

    if existing:
        # accepted a friend request, dispatch respective
        # relationship events
        await _dispatch(user_id, 'RELATIONSHIP_REMOVE', {
            'type': RelationshipType.INCOMING.value,
            'id': str(peer_id)
        })

        await _dispatch(user_id, 'RELATIONSHIP_ADD', {
            'type': _friend,
            'id': str(peer_id),
            'user': await app.storage.get_user(peer_id)
        })

        await _dispatch(peer_id, 'RELATIONSHIP_ADD', {
            'type': _friend,
            'id': str(user_id),
            'user': await app.storage.get_user(user_id)
        })

        return '', 204

    # check if friend AND not acceptance of fr
    if rel_type == _friend:
        await _dispatch(user_id, 'RELATIONSHIP_ADD', {
            'id': str(peer_id),
            'type': RelationshipType.OUTGOING.value,
            'user': await app.storage.get_user(peer_id),
        })

        await _dispatch(peer_id, 'RELATIONSHIP_ADD', {
            'id': str(user_id),
            'type': RelationshipType.INCOMING.value,
            'user': await app.storage.get_user(user_id)
        })

        return '', 204

    return


@bp.route('/@me/relationships', methods=['POST'])
async def post_relationship():
    user_id = await token_check()
    j = validate(await request.get_json(), SPECIFIC_FRIEND)

    uid = await app.storage.search_user(j['username'],
                                        str(j['discriminator']))

    if not uid:
        return '', 404

    res = await make_friend(user_id, uid)

    # NOTE: don't know what status code should I send
    if res is None:
        return '', 500

    return '', 204


@bp.route('/@me/relationships/<int:peer_id>', methods=['PUT'])
async def add_relationship(peer_id: int):
    """Add a relationship to the peer."""
    user_id = await token_check()
    payload = validate(await request.get_json(), RELATIONSHIP)
    rel_type = payload['type']

    res = await make_friend(user_id, peer_id, rel_type)

    if res is not None:
        return res

    # make_friend did not succeed, so we
    # assume it is a block and dispatch
    # the respective RELATIONSHIP_ADD.
    await app.dispatcher.dispatch_user(user_id, 'RELATIONSHIP_ADD', {
        'id': str(peer_id),
        'type': RelationshipType.BLOCK.value,
        'user': await app.storage.get_user(peer_id)
    })

    return '', 204


@bp.route('/@me/relationships/<int:peer_id>', methods=['DELETE'])
async def remove_relationship(peer_id: int):
    """Remove an existing relationship"""
    user_id = await token_check()
    _friend = RelationshipType.FRIEND.value
    _block = RelationshipType.BLOCK.value
    _dispatch = app.dispatcher.dispatch_user

    rel_type = await app.db.fetchval("""
    SELECT rel_type
    FROM relationships
    WHERE user_id = $1 AND peer_id = $2
    """, user_id, peer_id)

    incoming_rel_type = await app.db.fetchval("""
    SELECT rel_type
    FROM relationships
    WHERE user_id = $1 AND peer_id = $2
    """, peer_id, user_id)

    # if any of those are friend
    if _friend in (rel_type, incoming_rel_type):
        # closing the friendship, have to delete both rows
        await app.db.execute("""
        DELETE FROM relationships
        WHERE (
            (user_id = $1 AND peer_id = $2) OR
            (user_id = $2 AND peer_id = $1)
            ) AND rel_type = $3
        """, user_id, peer_id, _friend)

        # if there wasnt any mutual friendship before,
        # assume they were requests of INCOMING
        # and OUTGOING.
        user_del_type = RelationshipType.OUTGOING.value if \
            incoming_rel_type != _friend else _friend

        await _dispatch(user_id, 'RELATIONSHIP_REMOVE', {
            'id': str(peer_id),
            'type': user_del_type,
        })

        peer_del_type = RelationshipType.INCOMING.value if \
            incoming_rel_type != _friend else _friend

        await _dispatch(peer_id, 'RELATIONSHIP_REMOVE', {
            'id': str(user_id),
            'type': peer_del_type,
        })

        return '', 204

    # was a block!
    await app.db.execute("""
    DELETE FROM relationships
    WHERE user_id = $1 AND peer_id = $2 AND rel_type = $3
    """, user_id, peer_id, _block)

    await _dispatch(user_id, 'RELATIONSHIP_REMOVE', {
        'id': str(peer_id),
        'type': _block,
    })

    return '', 204

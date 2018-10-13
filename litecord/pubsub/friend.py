from logbook import Logger

from .dispatcher import DispatcherWithState

log = Logger(__name__)


class FriendDispatcher(DispatcherWithState):
    KEY_TYPE = int
    VAL_TYPE = int

    async def dispatch(self, user_id: int, event, data):
        """Dispatch an event to all of a users' friends."""
        peer_ids = self.state[user_id]
        dispatched = 0

        for peer_id in peer_ids:
            dispatched += await self.main_dispatcher.dispatch(
                'user', peer_id, event, data)

        log.info('dispatched uid={} {!r} to {} states',
                 user_id, event, dispatched)
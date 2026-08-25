# -*- coding: utf-8 -*-
"""Live realtime game framework — pluggable game engines.

A "live game" is a multiplayer session where a teacher hosts a game and
students join and play in realtime.  The framework (session, participants,
bus broadcasting, join/heartbeat flow) is game-agnostic; the actual game
rules live in an *engine* registered here.

Engines are plain Python classes registered in :data:`LIVE_GAME_ENGINES`
under a short ``game_type`` key.  Registering a new game is a matter of
subclassing :class:`LiveGameEngine` and decorating it with
:func:`register_engine` — no framework changes required.
"""

import logging

_logger = logging.getLogger(__name__)

# Registry of game engines: {game_type: engine_class}
LIVE_GAME_ENGINES = {}


def register_engine(game_type, label):
    """Class decorator registering a live game engine.

    :param str game_type: short unique key stored on ``live.game.session.game_type``
    :param str label: human readable game name shown in the UI
    """

    def _decorator(cls):
        if game_type in LIVE_GAME_ENGINES:
            _logger.warning(
                "Live game engine %r is being replaced by %s",
                game_type,
                cls.__name__,
            )
        cls.game_type = game_type
        cls.label = label
        LIVE_GAME_ENGINES[game_type] = cls
        return cls

    return _decorator


def get_engine(game_type):
    """Return the engine class registered for ``game_type``.

    :raises KeyError: when no engine is registered under that key.
    """
    try:
        return LIVE_GAME_ENGINES[game_type]
    except KeyError:
        raise KeyError(
            f"No live game engine registered for game_type={game_type!r}. "
            f"Known engines: {sorted(LIVE_GAME_ENGINES)}"
        ) from None


class LiveGameEngine:
    """Base class for live game engines.

    Engines implement the game-specific behaviour of a live session.  All
    methods receive the session/participant records and may rely on the
    framework for broadcasting (``session._broadcast``) and persistence.

    Class attributes (set by :func:`register_engine`):
        ``game_type``  short key stored on the session record
        ``label``      human readable game name
    """

    game_type = None
    label = None

    # ------------------------------------------------------------------
    # Session lifecycle hooks
    # ------------------------------------------------------------------
    def on_session_start(self, session):
        """Called when the host starts the session (state -> running)."""

    def on_session_finish(self, session):
        """Called when the host finishes the session (state -> finished)."""

    def on_participant_join(self, session, participant):
        """Called after a participant (re)joined the session."""

    # ------------------------------------------------------------------
    # Data hooks
    # ------------------------------------------------------------------
    def build_snapshot(self, session, participant=None):
        """Return the game-specific part of the state snapshot.

        The framework merges this with its own session/participant data
        before sending it to a client (on join, reconnect or heartbeat).
        """
        return {}

    def build_public_state(self, session):
        """Return the game-specific part of the broadcast state.

        Broadcast to the session bus channel whenever the session state
        changes (lobby, start, finish...).  Keep it small and free of
        anything that would leak answers.
        """
        return {}

    # ------------------------------------------------------------------
    # Gameplay hooks (engines with in-game RPCs override these)
    # ------------------------------------------------------------------
    def handle_rpc(self, session, participant, method, params) -> dict:
        """Handle a game-specific RPC from a participant.

        :param session: live.game.session record
        :param participant: live.game.participant record (the caller)
        :param str method: RPC method name sent by the client
        :param dict params: RPC parameters
        :return: JSON-serializable result dict
        :raises UserError: on invalid input / game rule violations
        """
        raise UserError(f"Game '{self.label}' does not support RPC method '{method}'.")
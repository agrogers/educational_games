# -*- coding: utf-8 -*-
"""HTTP/JSON endpoints for live realtime games.

Controllers stay thin: authentication, session lookup and permission checks
happen here; all game logic lives in the models/engines.
"""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json_response(payload, status=200):
    return request.make_json_response(payload, status=status)


class LiveGameController(http.Controller):

    # ------------------------------------------------------------------
    # Session lookup helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_session(session_id):
        session = request.env['live.game.session'].browse(int(session_id))
        if not session.exists():
            raise http.NotFound()
        return session

    @staticmethod
    def _get_session_by_code(access_code):
        session = request.env['live.game.session'].sudo().search([
            ('access_code', '=', (access_code or '').strip().upper()),
            ('state', 'in', ('lobby', 'running')),
        ], limit=1)
        if not session:
            raise http.NotFound()
        return session

    @staticmethod
    def _get_participant(session):
        """The caller's participant record for ``session`` (or None)."""
        return request.env['live.game.participant'].sudo().search([
            ('session_id', '=', session.id),
            ('user_id', '=', request.env.user.id),
        ], limit=1)

    # ------------------------------------------------------------------
    # JSON API
    # ------------------------------------------------------------------
    @http.route('/live_game/join', type='json', auth='user', csrf=False, cors='*')
    def join(self, access_code=None, **kwargs):
        """Join a session by its human code.  Returns snapshot + channel."""
        session = self._get_session_by_code(access_code)
        participant = session._join(request.env.user)
        return {
            'snapshot': session.get_snapshot(participant),
        }

    @http.route('/live_game/state', type='json', auth='user', csrf=False, cors='*')
    def state(self, session_id=None, **kwargs):
        """Full snapshot for reconnect / late load."""
        session = self._get_session(session_id)
        participant = self._get_participant(session)
        return {'snapshot': session.get_snapshot(participant)}

    @http.route('/live_game/heartbeat', type='json', auth='user', csrf=False, cors='*')
    def heartbeat(self, session_id=None, **kwargs):
        """Keep-alive + state fallback when the websocket is unavailable."""
        session = self._get_session(session_id)
        participant = self._get_participant(session)
        if participant:
            participant._touch()
        return {'snapshot': session.get_snapshot(participant)}

    @http.route('/live_game/game_rpc', type='json', auth='user', csrf=False, cors='*')
    def game_rpc(self, session_id=None, method=None, params=None, **kwargs):
        """Game-specific RPC dispatched to the session's engine."""
        session = self._get_session(session_id)
        if session.state not in ('lobby', 'running'):
            raise http.NotFound()
        participant = self._get_participant(session)
        if not participant:
            raise http.Forbidden()
        engine = session._get_engine()
        result = engine.handle_rpc(session, participant, method or '', params or {})
        return result

    # ------------------------------------------------------------------
    # Host actions (teacher)
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_host(session):
        if request.env.user.id != session.host_id.id and not request.env.user.has_group(
            'aps_sis.group_aps_teacher'
        ):
            raise http.Forbidden()

    @http.route('/live_game/host_action', type='json', auth='user', csrf=False, cors='*')
    def host_action(self, session_id=None, action=None, **kwargs):
        """Lobby/start/finish/cancel controls from the host console."""
        session = self._get_session(session_id)
        self._ensure_host(session)
        actions = {
            'open_lobby': session.action_open_lobby,
            'start': session.action_start,
            'finish': session.action_finish,
            'cancel': session.action_cancel,
        }
        if action not in actions:
            raise http.BadRequest()
        actions[action]()
        return {'snapshot': session.get_snapshot(self._get_participant(session))}

    # ------------------------------------------------------------------
    # Standalone pages
    # ------------------------------------------------------------------
    @http.route('/educational_games/live/host/<int:session_id>', type='http', auth='user')
    def host_page(self, session_id, **kwargs):
        """Full-screen host console (projector view)."""
        session = self._get_session(session_id)
        self._ensure_host(session)
        return request.render('educational_games.live_game_host_page', {
            'session_id': session.id,
            'session_name': session.name,
        })

    @http.route('/educational_games/live/play', type='http', auth='user')
    def play_page(self, **kwargs):
        """Full-screen student player.  The join code may be pre-filled
        from the query string (?code=ABCDE)."""
        return request.render('educational_games.live_game_play_page', {
            'default_code': (kwargs.get('code') or '').strip().upper(),
        })

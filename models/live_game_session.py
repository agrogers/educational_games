# -*- coding: utf-8 -*-
"""Live realtime game framework — game session model."""

import datetime
import random
import secrets
import string

from odoo import _, api, exceptions, fields, models

# Characters used for the human join code (no ambiguous 0/O/1/I).
_ACCESS_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCESS_CODE_LENGTH = 5

SESSION_STATES = [
    ('draft', 'Draft'),
    ('lobby', 'Lobby'),
    ('running', 'Running'),
    ('finished', 'Finished'),
    ('cancelled', 'Cancelled'),
]

# Sessions are vacuumed this long after they finish.
GC_DAYS = 7


class LiveGameSession(models.Model):
    _name = 'live.game.session'
    _description = 'Live Game Session'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Name', required=True)
    game_type = fields.Selection(
        selection='_selection_game_type',
        string='Game',
        required=True,
        index=True,
    )
    quiz_id = fields.Many2one(
        'quiz.quiz',
        string='Quiz',
        ondelete='set null',
        index=True,
        help='Question source for quiz-based games.',
    )
    config = fields.Json(string='Game Config', default=dict)
    state = fields.Selection(
        selection=SESSION_STATES,
        string='State',
        default='draft',
        required=True,
        index=True,
    )
    host_id = fields.Many2one(
        'res.users',
        string='Host',
        default=lambda self: self.env.user,
        required=True,
        index=True,
    )
    access_code = fields.Char(
        string='Join Code',
        copy=False,
        readonly=True,
        help='Human code students enter to join the session.',
    )
    bus_channel = fields.Char(
        string='Bus Channel',
        copy=False,
        readonly=True,
        help='Random non-guessable channel used for realtime broadcasts.',
    )
    participant_ids = fields.One2many(
        'live.game.participant',
        'session_id',
        string='Participants',
    )
    participant_count = fields.Integer(compute='_compute_participant_count')
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('participant_ids')
    def _compute_participant_count(self):
        for session in self:
            session.participant_count = len(session.participant_ids)

    @api.model
    def _selection_game_type(self):
        """Selection built from the engine registry so new games appear
        without touching this model."""
        from .live_game_engine import LIVE_GAME_ENGINES
        return [(key, engine.label) for key, engine in sorted(LIVE_GAME_ENGINES.items())]

    @api.constrains('config')
    def _check_config_is_object(self):
        for session in self:
            if session.config is not False and not isinstance(session.config, dict):
                raise exceptions.ValidationError(_("Game config must be a JSON object."))

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for session in sessions:
            if not session.bus_channel:
                session.bus_channel = self._generate_bus_channel()
        return sessions

    def copy(self, default=None):
        # A fresh session must not inherit the previous join code/channel.
        default = dict(default or {})
        default.setdefault('access_code', False)
        return super().copy(default)

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------
    @api.model
    def _generate_access_code(self):
        rng = random.SystemRandom()
        while True:
            code = ''.join(rng.choice(_ACCESS_CODE_ALPHABET) for _ in range(ACCESS_CODE_LENGTH))
            if not self.search_count([('access_code', '=', code)]):
                return code

    @api.model
    def _generate_bus_channel(self):
        return secrets.token_hex(16)

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------
    @api.autovacuum
    def _gc(self):
        """Delete finished/cancelled sessions older than GC_DAYS."""
        cutoff = fields.Datetime.now() - datetime.timedelta(days=GC_DAYS)
        stale = self.search([
            ('state', 'in', ['finished', 'cancelled']),
            ('write_date', '<', cutoff),
        ])
        stale.unlink()

    # ------------------------------------------------------------------
    # Engine access
    # ------------------------------------------------------------------
    def _get_engine(self):
        """Return the engine instance registered for this session's game type."""
        from .live_game_engine import get_engine
        self.ensure_one()
        return get_engine(self.game_type)()

    # ------------------------------------------------------------------
    # Lifecycle actions
    # ------------------------------------------------------------------
    def action_open_lobby(self):
        """Generate the join code and open the lobby (students can join)."""
        for session in self.filtered(lambda s: s.state == 'draft'):
            session.write({
                'access_code': session.access_code or self._generate_access_code(),
                'state': 'lobby',
            })
        self._broadcast_state()
        return True

    def action_start(self):
        """Start the game (state -> running)."""
        for session in self.filtered(lambda s: s.state == 'lobby'):
            session.write({'state': 'running', 'started_at': fields.Datetime.now()})
            session._get_engine().on_session_start(session)
        self._broadcast_state()
        return True

    def action_finish(self):
        """Finish the game and publish final standings."""
        for session in self.filtered(lambda s: s.state == 'running'):
            session.write({'state': 'finished', 'finished_at': fields.Datetime.now()})
            session._get_engine().on_session_finish(session)
        self._broadcast_state()
        return True

    def action_cancel(self):
        """Cancel the session; participants are notified."""
        for session in self.filtered(lambda s: s.state in ('draft', 'lobby', 'running')):
            session.write({'state': 'cancelled'})
        self._broadcast_state()
        return True

    def action_reopen_lobby(self):
        """Return a finished/cancelled session to the lobby with a fresh code."""
        for session in self.filtered(lambda s: s.state in ('finished', 'cancelled')):
            session.write({
                'access_code': self._generate_access_code(),
                'started_at': False,
                'finished_at': False,
                'state': 'lobby',
            })
            session.participant_ids.write({
                'score': 0,
                'progress': {},
                'position': 0.0,
                'state': 'joined',
            })
        self._broadcast_state()
        return True

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------
    def _broadcast(self, notification_type, payload):
        """Send ``payload`` to every client subscribed to this session's
        realtime channel via the Odoo websocket bus."""
        self.ensure_one()
        if not self.bus_channel:
            return False
        self.env['bus.bus']._sendone(self.bus_channel, notification_type, payload)
        return True

    def _broadcast_state(self):
        """Broadcast the public session state (lobby/start/finish...)."""
        for session in self:
            payload = {
                'type': 'lg_state',
                'session_id': session.id,
                'state': session.state,
                'access_code': session.access_code or '',
                **session._get_engine().build_public_state(session),
            }
            session._broadcast('lg_state', payload)

    def broadcast_progress(self, participant):
        """Broadcast one participant's progress (called by engines after a
        participant advances)."""
        self.ensure_one()
        self._broadcast('lg_progress', {
            'type': 'lg_progress',
            'session_id': self.id,
            'participant': participant._get_public_data(),
        })

    # ------------------------------------------------------------------
    # Joining / snapshots
    # ------------------------------------------------------------------
    def _join(self, user):
        """Join (or rejoin) ``user`` to this session.

        :return: live.game.participant record
        """
        self.ensure_one()
        if self.state not in ('lobby', 'running'):
            raise exceptions.UserError(_("This game is not accepting players right now."))
        if self.state == 'running' and not self.env['ir.config_parameter'].sudo().get_param(
            'educational_games.live_allow_late_join', default=True
        ):
            raise exceptions.UserError(_("This game has already started."))

        Participant = self.env['live.game.participant'].sudo()
        participant = Participant.search([
            ('session_id', '=', self.id),
            ('user_id', '=', user.id),
        ], limit=1)
        if participant:
            participant.last_seen = fields.Datetime.now()
        else:
            participant = Participant.create({
                'session_id': self.id,
                'user_id': user.id,
                'nickname': user.name,
                'avatar': self._pick_avatar(),
            })
        self._get_engine().on_participant_join(self, participant)
        # Everyone sees the newcomer immediately.
        self.broadcast_progress(participant)
        return participant

    def _pick_avatar(self):
        """Pick the least-used avatar so players get distinct icons."""
        taken = set(self.participant_ids.mapped('avatar'))
        available = [a for a in AVATAR_KEYS if a not in taken]
        if not available:
            return random.choice(AVATAR_KEYS)
        return available[0]

    def get_snapshot(self, participant=None):
        """Full state snapshot for a client (join/reconnect/heartbeat).

        :param participant: live.game.participant record of the requesting
            client, when authenticated as a participant.
        """
        self.ensure_one()
        engine = self._get_engine()
        snapshot = {
            'type': 'lg_snapshot',
            'session_id': self.id,
            'name': self.name,
            'game_type': self.game_type,
            'game_label': engine.label,
            'state': self.state,
            'access_code': self.access_code or '',
            'bus_channel': self.bus_channel,
            'participants': [
                p._get_public_data() for p in self.participant_ids.sorted(key='id')
            ],
            **engine.build_public_state(self),
        }
        if participant:
            snapshot['me'] = participant._get_private_data()
            snapshot.update(engine.build_snapshot(self, participant))
        return snapshot


# Avatars shared by session/participant models and the frontend.
AVATAR_KEYS = [
    'red', 'orange', 'yellow', 'green', 'teal',
    'blue', 'purple', 'pink', 'black', 'white',
]

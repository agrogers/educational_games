# -*- coding: utf-8 -*-
"""Live realtime game framework — participant model."""

from odoo import _, api, exceptions, fields, models

from .live_game_session import AVATAR_KEYS


class LiveGameParticipant(models.Model):
    _name = 'live.game.participant'
    _description = 'Live Game Participant'
    _order = 'position desc, score desc, id asc'

    session_id = fields.Many2one(
        'live.game.session',
        string='Session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Student',
        required=True,
        ondelete='cascade',
        index=True,
    )
    nickname = fields.Char(string='Nickname', required=True)
    avatar = fields.Selection(
        selection=[(key, key.title()) for key in AVATAR_KEYS],
        string='Avatar',
        default='red',
        required=True,
    )
    score = fields.Integer(string='Score', default=0)
    progress = fields.Json(string='Progress', default=dict)
    position = fields.Float(
        string='Position',
        default=0.0,
        help='Race progress as a percentage (0-100).',
    )
    state = fields.Selection(
        selection=[
            ('joined', 'Joined'),
            ('playing', 'Playing'),
            ('finished', 'Finished'),
        ],
        string='State',
        default='joined',
        required=True,
    )
    last_seen = fields.Datetime(string='Last Seen', default=fields.Datetime.now)

    _sql_constraints = [
        (
            'user_session_uniq',
            'unique(session_id, user_id)',
            'A student can only join a session once.',
        ),
    ]

    @api.constrains('avatar')
    def _check_avatar(self):
        for participant in self:
            if participant.avatar not in AVATAR_KEYS:
                raise exceptions.ValidationError(_("Unknown avatar: %s", participant.avatar))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def _get_public_data(self):
        """Data broadcast to every client about this participant."""
        self.ensure_one()
        return {
            'id': self.id,
            'user_id': self.user_id.id,
            'nickname': self.nickname,
            'avatar': self.avatar,
            'score': self.score,
            'position': round(self.position, 2),
            'state': self.state,
            'progress': self.progress or {},
        }

    def _get_private_data(self):
        """Data sent only to the participant themself."""
        data = self._get_public_data()
        data.update({
            'session_id': self.session_id.id,
            'last_seen': fields.Datetime.to_string(self.last_seen),
        })
        return data

    # ------------------------------------------------------------------
    # Progress helpers (used by engines)
    # ------------------------------------------------------------------
    def _update_progress(self, score=None, position=None, state=None, progress=None):
        """Persist progress and broadcast it to the session."""
        self.ensure_one()
        vals = {}
        if score is not None:
            vals['score'] = int(score)
        if position is not None:
            vals['position'] = max(0.0, min(100.0, float(position)))
        if state is not None:
            vals['state'] = state
        if progress is not None:
            vals['progress'] = progress
        if vals:
            self.write(vals)
        self.session_id.broadcast_progress(self)
        return self

    def _touch(self):
        self.last_seen = fields.Datetime.now()

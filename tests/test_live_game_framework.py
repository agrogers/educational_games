"""Tests for the live realtime game framework (session, participant, registry)."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLiveGameEngineRegistry(TransactionCase):

    def test_quiz_race_engine_registered(self):
        from odoo.addons.educational_games.models.live_game_engine import (
            LIVE_GAME_ENGINES,
            get_engine,
        )

        self.assertIn('quiz_race', LIVE_GAME_ENGINES)
        engine = get_engine('quiz_race')
        self.assertTrue(issubclass(engine, object))

    def test_unknown_engine_raises_keyerror(self):
        from odoo.addons.educational_games.models.live_game_engine import get_engine

        with self.assertRaises(KeyError):
            get_engine('no_such_game')


@tagged('post_install', '-at_install')
class TestLiveGameSessionLifecycle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.teacher = self.env['res.users'].create({
            'name': 'Teacher',
            'login': 'lg_teacher_%s' % fields.Datetime.now(),
            'groups_id': [(6, 0, [self.env.ref('aps_sis.group_aps_teacher').id])],
        })
        self.student_a = self.env['res.users'].create({
            'name': 'Student A',
            'login': 'lg_student_a_%s' % fields.Datetime.now(),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.student_b = self.env['res.users'].create({
            'name': 'Student B',
            'login': 'lg_student_b_%s' % fields.Datetime.now(),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.quiz = self.env['quiz.quiz'].create({'name': 'Live Quiz'})

    def _create_session(self, **kwargs):
        vals = {
            'name': 'Test Session',
            'game_type': 'quiz_race',
            'quiz_id': self.quiz.id,
        }
        vals.update(kwargs)
        return self.env['live.game.session'].create(vals)

    def test_create_generates_access_code_and_channel(self):
        session = self._create_session()
        self.assertEqual(len(session.access_code), 5)
        self.assertEqual(len(session.bus_channel), 32)
        self.assertEqual(session.state, 'draft')

    def test_access_code_excludes_ambiguous_characters(self):
        for _ in range(20):
            code = self.env['live.game.session']._generate_access_code()
            self.assertFalse(set(code) & set('0O1I'))

    def test_copy_clears_access_code(self):
        session = self._create_session()
        clone = session.copy()
        self.assertFalse(clone.access_code)
        self.assertNotEqual(clone.bus_channel, session.bus_channel)

    def test_full_lifecycle_broadcasts_state(self):
        session = self._create_session()
        session.action_open_lobby()
        self.assertEqual(session.state, 'lobby')
        session.action_start()
        self.assertEqual(session.state, 'running')
        session.action_finish()
        self.assertEqual(session.state, 'finished')

    def test_reopen_lobby_resets_running_session(self):
        session = self._create_session()
        session.action_open_lobby()
        session.action_start()
        session.action_reopen_lobby()
        self.assertEqual(session.state, 'lobby')

    def test_join_creates_participant_and_rejoin_restores(self):
        session = self._create_session()
        session.action_open_lobby()

        participant = session._join(self.student_a)
        self.assertEqual(participant.user_id, self.student_a)

        # Re-joining returns the same participant record.
        again = session._join(self.student_a)
        self.assertEqual(again.id, participant.id)
        self.assertEqual(len(session.participant_ids), 1)

    def test_join_rejected_when_not_in_lobby_or_running(self):
        session = self._create_session()  # draft
        with self.assertRaises(UserError):
            session._join(self.student_a)

    def test_get_snapshot_shape(self):
        session = self._create_session()
        session.action_open_lobby()
        snapshot = session.get_snapshot()
        self.assertEqual(snapshot['type'], 'lg_snapshot')
        self.assertEqual(snapshot['state'], 'lobby')
        self.assertIn('participants', snapshot)
        self.assertIn('bus_channel', snapshot)

    def test_gc_removes_old_finished_sessions_only(self):
        old = self._create_session(name='Old Finished')
        old.action_open_lobby()
        old.action_start()
        old.action_finish()
        # Backdate via SQL: the ORM recomputes write_date on write().
        self.env.cr.execute(
            "UPDATE live_game_session SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=8), old.id))
        old.invalidate_recordset()

        fresh = self._create_session(name='Fresh Finished')
        fresh.action_open_lobby()
        fresh.action_start()
        fresh.action_finish()

        running = self._create_session(name='Still Running')
        running.action_open_lobby()
        running.action_start()

        self.env['live.game.session']._gc()

        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(running.exists())


@tagged('post_install', '-at_install')
class TestLiveGameParticipant(TransactionCase):

    def setUp(self):
        super().setUp()
        self.session = self.env['live.game.session'].create({
            'name': 'Participant Session',
            'game_type': 'quiz_race',
        })
        self.participant = self.env['live.game.participant'].create({
            'session_id': self.session.id,
            'user_id': self.env.user.id,
            'nickname': 'Tester',
            'avatar': 'red',
        })

    def test_position_clamped_to_0_100(self):
        self.participant._update_progress(score=10, position=150, state='playing')
        self.assertEqual(self.participant.position, 100.0)
        self.participant._update_progress(score=10, position=-5, state='playing')
        self.assertEqual(self.participant.position, 0.0)

    def test_duplicate_user_per_session_forbidden(self):
        with self.assertRaises(Exception):
            self.env['live.game.participant'].create({
                'session_id': self.session.id,
                'user_id': self.env.user.id,
                'nickname': 'Dup',
                'avatar': 'blue',
            })

    def test_invalid_avatar_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['live.game.participant'].create({
                'session_id': self.session.id,
                'user_id': self.env.user.id,
                'nickname': 'BadAvatar',
                'avatar': 'chartreuse',
            })

    def test_public_data_fields(self):
        data = self.participant._get_public_data()
        for key in ('id', 'user_id', 'nickname', 'avatar', 'score', 'position', 'state'):
            self.assertIn(key, data)


@tagged('post_install', '-at_install')
class TestLiveGameAccessRights(TransactionCase):

    def test_regular_user_cannot_create_sessions(self):
        user = self.env['res.users'].create({
            'name': 'Plain User',
            'login': 'lg_plain_%s' % fields.Datetime.now(),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['live.game.session'].with_user(user).create({
                'name': 'Sneaky Session',
                'game_type': 'quiz_race',
            })

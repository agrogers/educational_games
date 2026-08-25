"""Tests for the Quiz Race live game engine."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuizRaceEngine(TransactionCase):

    def setUp(self):
        super().setUp()
        self.quiz = self.env['quiz.quiz'].create({'name': 'Race Quiz'})
        self.questions = self.env['quiz.question']
        for index in range(3):
            question = self.env['quiz.question'].create({
                'question_text': 'Q%s' % index,
            })
            for answer_index in range(4):
                self.env['quiz.answer'].create({
                    'question_id': question.id,
                    'answer_text': 'A%s-%s' % (index, answer_index),
                    'is_correct': answer_index == 0,
                })
            self.questions += question
        self.quiz.write({'question_ids': [(6, 0, self.questions.ids)]})

        self.session = self.env['live.game.session'].create({
            'name': 'Engine Session',
            'game_type': 'quiz_race',
            'quiz_id': self.quiz.id,
        })
        self.student = self.env['res.users'].create({
            'name': 'Racer',
            'login': 'racer_%s' % fields.Datetime.now(),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.session.action_open_lobby()
        self.participant = self.session._join(self.student)
        self.session.action_start()
        self.engine = self.session._get_engine()

    def _correct_ids_for(self, question):
        return self.env['quiz.answer'].browse(
            [a['id'] for a in question['answers']]).filtered('is_correct').ids

    def _submit_correct(self):
        question = self.engine.get_question(self.session, self.participant)
        correct_ids = self._correct_ids_for(question)
        return self.engine.handle_rpc(
            self.session, self.participant,
            'submit_answer', {'answer_ids': correct_ids})

    # ------------------------------------------------------------------
    # Question sanitization
    # ------------------------------------------------------------------
    def test_get_question_never_leaks_is_correct(self):
        question = self.engine.get_question(self.session, self.participant)
        self.assertNotIn('is_correct', question)
        for answer in question['answers']:
            self.assertNotIn('is_correct', answer)
            self.assertIn('answer_text', answer)

    def test_get_question_includes_metadata(self):
        question = self.engine.get_question(self.session, self.participant)
        self.assertEqual(question['index'], 0)
        self.assertEqual(question['total'], 3)
        self.assertEqual(len(question['answers']), 4)
        self.assertIn('asked_at', question)

    # ------------------------------------------------------------------
    # Ordering
    # ------------------------------------------------------------------
    def test_shuffle_deterministic_for_same_session(self):
        first = self.engine.get_question(self.session, self.participant)
        second = self.engine.get_question(self.session, self.participant)
        self.assertEqual(first['id'], second['id'])

    def test_configured_order_respected(self):
        reversed_ids = list(reversed(self.questions.ids))
        self.session.config = dict(self.session.config or {}, question_order=reversed_ids)
        engine = self.session._get_engine()
        question = engine.get_question(self.session, self.participant)
        self.assertEqual(question['id'], reversed_ids[0])

    # ------------------------------------------------------------------
    # Scoring and progression
    # ------------------------------------------------------------------
    def test_correct_answer_scores_and_advances(self):
        result = self._submit_correct()
        self.assertTrue(result['correct'])
        self.assertGreaterEqual(result['points_earned'], 100)
        self.assertEqual(result['next_index'], 1)
        self.assertFalse(result['finished'])
        self.assertEqual(self.participant.score, result['points_earned'])
        self.assertGreater(self.participant.position, 0)

    def test_wrong_answer_scores_zero_but_advances(self):
        question = self.engine.get_question(self.session, self.participant)
        all_answers = self.env['quiz.answer'].browse(
            [a['id'] for a in question['answers']])
        wrong_ids = all_answers.filtered(lambda a: not a.is_correct)[:1].ids
        result = self.engine.handle_rpc(
            self.session, self.participant,
            'submit_answer', {'answer_ids': wrong_ids})
        self.assertFalse(result['correct'])
        self.assertEqual(result['points_earned'], 0)
        self.assertEqual(result['next_index'], 1)

    def test_double_submit_is_idempotent(self):
        first = self._submit_correct()
        replay = self.engine.handle_rpc(
            self.session, self.participant,
            'submit_answer', {'answer_ids': []})
        self.assertEqual(replay['correct'], first['correct'])
        self.assertEqual(replay['score'], first['score'])

    def test_finish_after_last_question(self):
        for _ in range(3):
            result = self._submit_correct()
        self.assertTrue(result['finished'])
        self.assertEqual(self.participant.state, 'finished')
        self.assertEqual(self.participant.position, 100.0)

    def test_submit_rejected_when_not_running(self):
        self.session.action_finish()
        with self.assertRaises(UserError):
            self.engine.handle_rpc(
                self.session, self.participant,
                'submit_answer', {'answer_ids': []})

    def test_unknown_rpc_method_raises(self):
        with self.assertRaises(UserError):
            self.engine.handle_rpc(
                self.session, self.participant, 'no_such_method', {})

import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestQuizBulkAddCheck(TransactionCase):

    def test_bulk_check_stages_questions_and_requests_reload(self):
        question = self.env['quiz.question'].create({
            'question_text': 'Question for bulk add',
        })
        quiz = self.env['quiz.quiz'].create({
            'name': 'Bulk Add Quiz',
            'bulk_add_question_ids_text': str(question.id),
        })

        action = quiz.action_bulk_check_question_ids()

        self.assertEqual(quiz.bulk_add_question_ids.ids, [question.id])
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['next'], {'type': 'ir.actions.client', 'tag': 'reload'})


class TestQuizTokenFilters(TransactionCase):

    def test_get_quiz_for_student_applies_static_filters_and_returns_summary(self):
        subject_science = self.env['aps.subject'].create({'name': 'Science'})
        subject_history = self.env['aps.subject'].create({'name': 'History'})
        tag_focus = self.env['quiz.tag'].create({'name': 'Focus'})
        tag_other = self.env['quiz.tag'].create({'name': 'Other'})

        question_match = self.env['quiz.question'].create({
            'question_text': 'Target question',
            'subject_ids': [(6, 0, [subject_science.id])],
            'tag_ids': [(6, 0, [tag_focus.id])],
        })
        question_match.write({'attempt_count': 3, 'pct_correct_all': 45.0})

        question_wrong_subject = self.env['quiz.question'].create({
            'question_text': 'Wrong subject question',
            'subject_ids': [(6, 0, [subject_history.id])],
            'tag_ids': [(6, 0, [tag_focus.id])],
        })
        question_wrong_subject.write({'attempt_count': 3, 'pct_correct_all': 45.0})

        question_too_easy = self.env['quiz.question'].create({
            'question_text': 'Too easy question',
            'subject_ids': [(6, 0, [subject_science.id])],
            'tag_ids': [(6, 0, [tag_other.id])],
        })
        question_too_easy.write({'attempt_count': 7, 'pct_correct_all': 90.0})

        quiz = self.env['quiz.quiz'].create({
            'name': 'Filtered Quiz',
            'question_ids': [(6, 0, [question_match.id, question_wrong_subject.id, question_too_easy.id])],
            'filter_tag_ids': [(6, 0, [tag_focus.id])],
            'filter_subject_ids': [(6, 0, [subject_science.id])],
            'filter_min_attempts': '2',
            'filter_max_attempts': '5',
            'filter_max_pct_correct': '50',
        })

        token = quiz._build_quiz_token(
            quiz.id,
            filter_payload=quiz._get_quiz_filter_payload(),
        )
        payload = quiz.get_quiz_for_student(quiz.id, quiz_token=token)

        self.assertEqual([question['id'] for question in payload['questions']], [question_match.id])
        self.assertIn('Subjects: Science', payload['filter_summary'])
        self.assertIn('Tags: Focus', payload['filter_summary'])
        self.assertIn('Attempts between 2 and 5', payload['filter_summary'])
        self.assertIn('Overall % correct at most 50%', payload['filter_summary'])

    def test_student_attempts_and_weighted_score_filters_use_and_logic(self):
        quiz = self.env['quiz.quiz'].create({
            'name': 'Student Filter Quiz',
            'filter_student_attempts': '2',
            'filter_student_weighted_score_pct': '60',
        })

        question_keep = self.env['quiz.question'].create({'question_text': 'Keep me'})
        answer_keep_correct = self.env['quiz.answer'].create({
            'question_id': question_keep.id,
            'answer_text': 'Correct keep',
            'is_correct': True,
        })
        answer_keep_wrong = self.env['quiz.answer'].create({
            'question_id': question_keep.id,
            'answer_text': 'Wrong keep',
            'is_correct': False,
        })

        question_exclude = self.env['quiz.question'].create({'question_text': 'Exclude me'})
        answer_exclude_correct = self.env['quiz.answer'].create({
            'question_id': question_exclude.id,
            'answer_text': 'Correct exclude',
            'is_correct': True,
        })
        answer_exclude_wrong = self.env['quiz.answer'].create({
            'question_id': question_exclude.id,
            'answer_text': 'Wrong exclude',
            'is_correct': False,
        })

        quiz.question_ids = [(6, 0, [question_keep.id, question_exclude.id])]

        response_model = self.env['quiz.response']
        for answer in [answer_keep_correct, answer_keep_wrong, answer_keep_wrong]:
            response_model.create({
                'quiz_id': quiz.id,
                'question_id': question_keep.id,
                'answer_id': answer.id,
                'user_id': self.env.user.id,
                'attempt_token': uuid.uuid4().hex,
                'is_correct': answer.is_correct,
            })
        for answer in [answer_exclude_wrong, answer_exclude_correct, answer_exclude_correct]:
            response_model.create({
                'quiz_id': quiz.id,
                'question_id': question_exclude.id,
                'answer_id': answer.id,
                'user_id': self.env.user.id,
                'attempt_token': uuid.uuid4().hex,
                'is_correct': answer.is_correct,
            })

        token = quiz._build_quiz_token(
            quiz.id,
            filter_payload=quiz._get_quiz_filter_payload(),
        )
        payload = quiz.get_quiz_for_student(quiz.id, quiz_token=token)

        self.assertEqual([question['id'] for question in payload['questions']], [question_keep.id])
        self.assertEqual(payload['questions'][0]['student_attempt_count'], 3)
        self.assertEqual(payload['questions'][0]['student_weighted_score_pct'], 55)
        self.assertIn(
            'Exclude if all of these are true: your attempts are at least 2 and your weighted score is at least 60%',
            payload['filter_summary'],
        )

    def test_quiz_progress_summary_uses_static_scope_and_student_thresholds(self):
        subject_science = self.env['aps.subject'].create({'name': 'Science'})
        subject_history = self.env['aps.subject'].create({'name': 'History'})
        tag_focus = self.env['quiz.tag'].create({'name': 'Focus'})
        tag_other = self.env['quiz.tag'].create({'name': 'Other'})

        question_known = self.env['quiz.question'].create({
            'question_text': 'Known question',
            'subject_ids': [(6, 0, [subject_science.id])],
            'tag_ids': [(6, 0, [tag_focus.id])],
        })
        question_unknown = self.env['quiz.question'].create({
            'question_text': 'Unknown question',
            'subject_ids': [(6, 0, [subject_science.id])],
            'tag_ids': [(6, 0, [tag_focus.id])],
        })
        question_not_tried_enough = self.env['quiz.question'].create({
            'question_text': 'Not tried enough question',
            'subject_ids': [(6, 0, [subject_science.id])],
            'tag_ids': [(6, 0, [tag_focus.id])],
        })
        question_filtered_out = self.env['quiz.question'].create({
            'question_text': 'Filtered out question',
            'subject_ids': [(6, 0, [subject_history.id])],
            'tag_ids': [(6, 0, [tag_other.id])],
        })

        quiz = self.env['quiz.quiz'].create({
            'name': 'Progress Summary Quiz',
            'question_ids': [
                (6, 0, [
                    question_known.id,
                    question_unknown.id,
                    question_not_tried_enough.id,
                    question_filtered_out.id,
                ])
            ],
            'filter_tag_ids': [(6, 0, [tag_focus.id])],
            'filter_subject_ids': [(6, 0, [subject_science.id])],
            'filter_student_attempts': '2',
            'filter_student_weighted_score_pct': '75',
        })

        response_model = self.env['quiz.response']
        known_correct = self.env['quiz.answer'].create({
            'question_id': question_known.id,
            'answer_text': 'Known correct',
            'is_correct': True,
        })
        self.env['quiz.answer'].create({
            'question_id': question_known.id,
            'answer_text': 'Known wrong',
            'is_correct': False,
        })
        unknown_wrong = self.env['quiz.answer'].create({
            'question_id': question_unknown.id,
            'answer_text': 'Unknown wrong',
            'is_correct': False,
        })
        unknown_correct = self.env['quiz.answer'].create({
            'question_id': question_unknown.id,
            'answer_text': 'Unknown correct',
            'is_correct': True,
        })
        tried_enough_correct = self.env['quiz.answer'].create({
            'question_id': question_not_tried_enough.id,
            'answer_text': 'Not tried enough correct',
            'is_correct': True,
        })
        self.env['quiz.answer'].create({
            'question_id': question_not_tried_enough.id,
            'answer_text': 'Not tried enough wrong',
            'is_correct': False,
        })

        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_known.id,
            'answer_id': known_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_known.id,
            'answer_id': known_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_unknown.id,
            'answer_id': unknown_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_unknown.id,
            'answer_id': unknown_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_not_tried_enough.id,
            'answer_id': tried_enough_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })

        token = quiz._build_quiz_token(
            quiz.id,
            filter_payload=quiz._get_quiz_filter_payload(),
        )
        payload = quiz.get_quiz_for_student(quiz.id, quiz_token=token)

        summary = payload['student_progress_summary']
        self.assertEqual(summary['total_possible_questions'], 3)
        self.assertEqual(summary['questions_with_results_data'], 2)
        self.assertEqual(summary['known_questions'], 1)
        self.assertEqual(summary['not_known_questions'], 1)
        self.assertEqual(summary['not_tried_enough_questions'], 1)
        self.assertIn('There are 3 questions in this quiz.', summary['progress_text'])
        self.assertIn('You have scored 75% or more in 1 out of the 2 we have results data for', summary['progress_text'])

    def test_quiz_progress_summary_defaults_to_eighty_percent(self):
        quiz = self.env['quiz.quiz'].create({
            'name': 'Default Threshold Quiz',
        })

        question_known = self.env['quiz.question'].create({'question_text': 'Known by default threshold'})
        question_not_known = self.env['quiz.question'].create({'question_text': 'Not known by default threshold'})
        quiz.question_ids = [(6, 0, [question_known.id, question_not_known.id])]

        known_correct = self.env['quiz.answer'].create({
            'question_id': question_known.id,
            'answer_text': 'Known correct',
            'is_correct': True,
        })
        known_wrong = self.env['quiz.answer'].create({
            'question_id': question_known.id,
            'answer_text': 'Known wrong',
            'is_correct': False,
        })
        not_known_correct = self.env['quiz.answer'].create({
            'question_id': question_not_known.id,
            'answer_text': 'Not known correct',
            'is_correct': True,
        })
        not_known_wrong = self.env['quiz.answer'].create({
            'question_id': question_not_known.id,
            'answer_text': 'Not known wrong',
            'is_correct': False,
        })

        response_model = self.env['quiz.response']
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_known.id,
            'answer_id': known_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_known.id,
            'answer_id': known_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_known.id,
            'answer_id': known_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_not_known.id,
            'answer_id': not_known_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })

        payload = quiz.get_quiz_for_student(quiz.id)

        summary = payload['student_progress_summary']
        self.assertEqual(summary['student_weighted_threshold'], 80)
        self.assertEqual(summary['questions_with_results_data'], 2)
        self.assertEqual(summary['known_questions'], 1)
        self.assertIn('You have scored 80% or more in 1 out of the 2 we have results data for.', summary['progress_text'])

    def test_exclude_answered_days_is_anded_with_other_student_filters(self):
        quiz = self.env['quiz.quiz'].create({
            'name': 'Combined Student Filter Quiz',
            'filter_student_attempts': '2',
            'filter_student_weighted_score_pct': '75',
            'filter_exclude_answered_days': '4',
        })

        question_not_recent = self.env['quiz.question'].create({'question_text': 'Keep not recent'})
        answer_not_recent_correct = self.env['quiz.answer'].create({
            'question_id': question_not_recent.id,
            'answer_text': 'Correct not recent',
            'is_correct': True,
        })
        answer_not_recent_wrong = self.env['quiz.answer'].create({
            'question_id': question_not_recent.id,
            'answer_text': 'Wrong not recent',
            'is_correct': False,
        })

        question_low_weighted = self.env['quiz.question'].create({'question_text': 'Keep low weighted'})
        answer_low_weighted_correct = self.env['quiz.answer'].create({
            'question_id': question_low_weighted.id,
            'answer_text': 'Correct low weighted',
            'is_correct': True,
        })
        answer_low_weighted_wrong = self.env['quiz.answer'].create({
            'question_id': question_low_weighted.id,
            'answer_text': 'Wrong low weighted',
            'is_correct': False,
        })

        question_exclude = self.env['quiz.question'].create({'question_text': 'Exclude only when all match'})
        answer_exclude_correct = self.env['quiz.answer'].create({
            'question_id': question_exclude.id,
            'answer_text': 'Correct exclude',
            'is_correct': True,
        })
        answer_exclude_wrong = self.env['quiz.answer'].create({
            'question_id': question_exclude.id,
            'answer_text': 'Wrong exclude',
            'is_correct': False,
        })

        quiz.question_ids = [(6, 0, [question_not_recent.id, question_low_weighted.id, question_exclude.id])]

        response_model = self.env['quiz.response']
        old_response = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_not_recent.id,
            'answer_id': answer_not_recent_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })
        old_response_2 = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_not_recent.id,
            'answer_id': answer_not_recent_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        low_weighted_response_1 = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_low_weighted.id,
            'answer_id': answer_low_weighted_wrong.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })
        low_weighted_response_2 = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_low_weighted.id,
            'answer_id': answer_low_weighted_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        recent_response_1 = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_exclude.id,
            'answer_id': answer_exclude_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })
        recent_response_2 = response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_exclude.id,
            'answer_id': answer_exclude_correct.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })

        old_response.write({'create_date': fields.Datetime.now() - timedelta(days=10)})
        old_response_2.write({'create_date': fields.Datetime.now() - timedelta(days=9)})
        low_weighted_response_1.write({'create_date': fields.Datetime.now() - timedelta(days=2)})
        low_weighted_response_2.write({'create_date': fields.Datetime.now() - timedelta(days=1)})
        recent_response_1.write({'create_date': fields.Datetime.now() - timedelta(days=2)})
        recent_response_2.write({'create_date': fields.Datetime.now() - timedelta(days=1)})

        token = quiz._build_quiz_token(
            quiz.id,
            filter_payload=quiz._get_quiz_filter_payload(),
        )
        payload = quiz.get_quiz_for_student(quiz.id, quiz_token=token)

        self.assertEqual(
            [question['id'] for question in payload['questions']],
            [question_not_recent.id, question_low_weighted.id],
        )
        self.assertIn(
            'Exclude if all of these are true: your attempts are at least 2 and your weighted score is at least 75% and you answered it in the previous 4 days',
            payload['filter_summary'],
        )


class TestQuizSubmissionScoring(TransactionCase):

    def _make_question(self, quiz, question_text):
        question = self.env['quiz.question'].create({
            'question_text': question_text,
            'quiz_id': quiz.id,
        })
        correct = self.env['quiz.answer'].create({
            'question_id': question.id,
            'answer_text': f'{question_text} correct',
            'is_correct': True,
        })
        self.env['quiz.answer'].create({
            'question_id': question.id,
            'answer_text': f'{question_text} wrong',
            'is_correct': False,
        })
        return question, correct

    def test_unfiltered_partial_submission_excludes_unanswered_questions(self):
        quiz = self.env['quiz.quiz'].create({'name': 'No Filter Quiz'})
        question_1, correct_1 = self._make_question(quiz, 'Question 1')
        question_2, _correct_2 = self._make_question(quiz, 'Question 2')
        question_3, _correct_3 = self._make_question(quiz, 'Question 3')
        quiz.question_ids = [(6, 0, [question_1.id, question_2.id, question_3.id])]

        result = quiz.submit_quiz_answers(quiz.id, {
            str(question_1.id): [correct_1.id],
            str(question_2.id): [],
            str(question_3.id): [],
        })

        self.assertEqual(result['score'], 1)
        self.assertEqual(result['total_marks'], 1)
        self.assertEqual([entry['question_id'] for entry in result['results']], [question_1.id])

    def test_filtered_partial_submission_excludes_unanswered_questions(self):
        quiz = self.env['quiz.quiz'].create({'name': 'Filtered Quiz'})
        question_1, correct_1 = self._make_question(quiz, 'Question 1')
        question_2, _correct_2 = self._make_question(quiz, 'Question 2')
        question_3, _correct_3 = self._make_question(quiz, 'Question 3')
        quiz.question_ids = [(6, 0, [question_1.id, question_2.id, question_3.id])]
        token = quiz._build_quiz_token(quiz.id, question_count=2)

        result = quiz.submit_quiz_answers(
            quiz.id,
            {
                str(question_1.id): [correct_1.id],
                str(question_2.id): [],
            },
            quiz_token=token,
        )

        self.assertEqual(result['score'], 1)
        self.assertEqual(result['total_marks'], 1)
        self.assertEqual([entry['question_id'] for entry in result['results']], [question_1.id])

    def test_submit_returns_refreshed_student_progress_stats(self):
        quiz = self.env['quiz.quiz'].create({
            'name': 'Progress Refresh Quiz',
            'filter_student_attempts': '1',
            'filter_student_weighted_score_pct': '50',
        })
        question_1, correct_1 = self._make_question(quiz, 'Question 1')
        question_2, _correct_2 = self._make_question(quiz, 'Question 2')
        quiz.question_ids = [(6, 0, [question_1.id, question_2.id])]

        response_model = self.env['quiz.response']
        response_model.create({
            'quiz_id': quiz.id,
            'question_id': question_1.id,
            'answer_id': correct_1.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': True,
        })

        result = quiz.submit_quiz_answers(
            quiz.id,
            {
                str(question_1.id): [correct_1.id],
                str(question_2.id): [],
            },
        )

        self.assertIn('student_question_stats', result)
        self.assertIn('student_progress_summary', result)
        self.assertEqual(result['student_question_stats'][str(question_1.id)]['attempt_count'], 2)


class TestQuizInheritQuestions(TransactionCase):
    """Tests for include_other_quizzes: question inheritance and circular reference guard."""

    def _make_quiz(self, name, questions=None):
        vals = {'name': name}
        if questions:
            vals['question_ids'] = [(6, 0, [q.id for q in questions])]
        return self.env['quiz.quiz'].create(vals)

    def _make_question(self, text):
        return self.env['quiz.question'].create({'question_text': text})

    # ── Inheritance ────────────────────────────────────────────────────────

    def test_effective_questions_includes_own_and_inherited(self):
        q1 = self._make_question('Own question')
        q2 = self._make_question('Inherited question')
        source = self._make_quiz('Source Quiz', questions=[q2])
        quiz = self._make_quiz('Main Quiz', questions=[q1])
        quiz.include_other_quizzes = [(4, source.id)]

        effective = quiz._get_effective_question_ids()
        self.assertIn(q1.id, effective.ids)
        self.assertIn(q2.id, effective.ids)

    def test_question_count_includes_inherited_questions(self):
        q1 = self._make_question('Own')
        q2 = self._make_question('Inherited')
        source = self._make_quiz('Source', questions=[q2])
        quiz = self._make_quiz('Main', questions=[q1])
        quiz.include_other_quizzes = [(4, source.id)]

        self.assertEqual(quiz.question_count, 2)

    def test_total_marks_includes_inherited_questions(self):
        q1 = self._make_question('Own')
        q1.marks = 2
        q2 = self._make_question('Inherited')
        q2.marks = 3
        source = self._make_quiz('Source', questions=[q2])
        quiz = self._make_quiz('Main', questions=[q1])
        quiz.include_other_quizzes = [(4, source.id)]

        self.assertEqual(quiz.total_marks, 5)

    def test_get_quiz_for_student_serves_inherited_questions(self):
        q1 = self._make_question('Own question')
        q2 = self._make_question('Inherited question')
        self.env['quiz.answer'].create({'question_id': q2.id, 'answer_text': 'A', 'is_correct': True})
        source = self._make_quiz('Source', questions=[q2])
        quiz = self._make_quiz('Main', questions=[q1])
        quiz.include_other_quizzes = [(4, source.id)]

        payload = quiz.get_quiz_for_student(quiz.id)
        returned_ids = {q['id'] for q in payload['questions']}
        self.assertIn(q1.id, returned_ids)
        self.assertIn(q2.id, returned_ids)

    def test_inherited_questions_added_later_are_also_included(self):
        """Questions added to a source quiz after inclusion are served correctly."""
        q_initial = self._make_question('Initial inherited question')
        source = self._make_quiz('Source', questions=[q_initial])
        quiz = self._make_quiz('Main')
        quiz.include_other_quizzes = [(4, source.id)]

        q_later = self._make_question('Later added question')
        source.question_ids = [(4, q_later.id)]

        effective = quiz._get_effective_question_ids()
        self.assertIn(q_initial.id, effective.ids)
        self.assertIn(q_later.id, effective.ids)

    def test_no_duplicate_questions_when_own_and_inherited_overlap(self):
        """A question that is both directly in the quiz and in an included quiz
        should appear only once in the effective question set."""
        q_shared = self._make_question('Shared question')
        source = self._make_quiz('Source', questions=[q_shared])
        quiz = self._make_quiz('Main', questions=[q_shared])
        quiz.include_other_quizzes = [(4, source.id)]

        effective = quiz._get_effective_question_ids()
        self.assertEqual(effective.ids.count(q_shared.id), 1)

    def test_transitive_inheritance(self):
        """Quiz A includes B which includes C — A should see C's questions."""
        q_c = self._make_question('Question in C')
        quiz_c = self._make_quiz('Quiz C', questions=[q_c])
        quiz_b = self._make_quiz('Quiz B')
        quiz_b.include_other_quizzes = [(4, quiz_c.id)]
        quiz_a = self._make_quiz('Quiz A')
        quiz_a.include_other_quizzes = [(4, quiz_b.id)]

        effective = quiz_a._get_effective_question_ids()
        self.assertIn(q_c.id, effective.ids)

    # ── Circular reference ─────────────────────────────────────────────────

    def test_direct_circular_reference_is_rejected(self):
        from odoo.exceptions import ValidationError
        quiz_a = self._make_quiz('Quiz A')
        quiz_b = self._make_quiz('Quiz B')
        quiz_a.include_other_quizzes = [(4, quiz_b.id)]

        with self.assertRaises(ValidationError):
            quiz_b.include_other_quizzes = [(4, quiz_a.id)]

    def test_indirect_circular_reference_is_rejected(self):
        from odoo.exceptions import ValidationError
        quiz_a = self._make_quiz('Quiz A')
        quiz_b = self._make_quiz('Quiz B')
        quiz_c = self._make_quiz('Quiz C')
        quiz_a.include_other_quizzes = [(4, quiz_b.id)]
        quiz_b.include_other_quizzes = [(4, quiz_c.id)]

        with self.assertRaises(ValidationError):
            quiz_c.include_other_quizzes = [(4, quiz_a.id)]

    def test_self_include_is_rejected(self):
        from odoo.exceptions import ValidationError
        quiz_a = self._make_quiz('Quiz A')

        with self.assertRaises(ValidationError):
            quiz_a.include_other_quizzes = [(4, quiz_a.id)]
        self.assertEqual(result['student_progress_summary']['total_possible_questions'], 2)
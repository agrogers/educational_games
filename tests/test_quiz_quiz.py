import uuid

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
        self.assertIn('Exclude if your attempts are at least 2 and your weighted score is at least 60%', payload['filter_summary'])


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

    def test_unfiltered_partial_submission_uses_minimum_out_of_ten(self):
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
        self.assertEqual(result['total_marks'], 10)

    def test_filtered_partial_submission_keeps_displayed_total(self):
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
        self.assertEqual(result['total_marks'], 2)
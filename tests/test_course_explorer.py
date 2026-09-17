import uuid

from odoo.tests.common import TransactionCase


class TestCourseExplorerQuizProgress(TransactionCase):

    def setUp(self):
        super().setUp()
        self.subject = self.env['aps.subject'].create({'name': 'Course Explorer English'})
        self.other_subject = self.env['aps.subject'].create({'name': 'Course Explorer Science'})
        self.resource = self.env['aps.resources'].create({
            'name': 'Chapter 1 Lesson',
            'has_notes': 'yes',
            'notes': '<p>Lesson notes</p>',
            'show_in_hierarchy': True,
            'subjects': [(6, 0, [self.subject.id])],
        })
        resource_tag = self.env['aps.resource.tags'].create({'name': ' Ch1 '})
        self.resource.write({'tag_ids': [(6, 0, [resource_tag.id])]})
        self.quiz = self.env['quiz.quiz'].create({'name': 'Chapter 1 Games'})
        self.questions = self._make_questions()
        self.quiz.write({'question_ids': [(6, 0, self.questions.ids)]})

    def _make_questions(self):
        chapter_tag = self.env['quiz.tag'].create({'name': 'ch1'})
        questions = self.env['quiz.question'].create([
            {
                'question_text': 'Question 1',
                'subject_ids': [(6, 0, [self.subject.id])],
                'tag_ids': [(6, 0, [chapter_tag.id])],
            },
            {
                'question_text': 'Question 2',
                'subject_ids': [(6, 0, [self.subject.id])],
                'tag_ids': [(6, 0, [chapter_tag.id])],
            },
            {
                'question_text': 'Question 3',
                'subject_ids': [(6, 0, [self.other_subject.id])],
                'tag_ids': [(6, 0, [chapter_tag.id])],
            },
        ])
        for question in questions:
            self.env['quiz.answer'].create({
                'question_id': question.id,
                'answer_text': 'Answer',
                'is_correct': False,
            })
        return questions

    def _progress(self):
        data = self.env['aps.resources'].get_course_explorer_progress(
            self.env.user.partner_id.id,
        )
        return data[self.resource.id]

    def _answer(self, question):
        answer = question.answer_ids[:1]
        self.env['quiz.response'].create({
            'quiz_id': self.quiz.id,
            'question_id': question.id,
            'answer_id': answer.id,
            'user_id': self.env.user.id,
            'attempt_token': uuid.uuid4().hex,
            'is_correct': False,
        })

    def test_question_responses_supply_half_progress(self):
        progress = self._progress()
        self.assertEqual(progress['quizQuestionCount'], 2)
        self.assertEqual(progress['quizAnsweredQuestionCount'], 0)
        self.assertEqual(progress['quizProgress'], 0.0)

        self._answer(self.questions[0])
        progress = self._progress()
        self.assertEqual(progress['quizAnsweredQuestionCount'], 1)
        self.assertEqual(progress['quizProgress'], 25.0)

        self._answer(self.questions[1])
        progress = self._progress()
        self.assertEqual(progress['quizAnsweredQuestionCount'], 2)
        self.assertEqual(progress['quizProgress'], 50.0)

    def test_no_matching_questions_completes_quiz_half(self):
        self.resource.write({'tag_ids': [(5, 0, 0)]})
        progress = self._progress()
        self.assertEqual(progress['quizQuestionCount'], 0)
        self.assertEqual(progress['quizProgress'], 0.0)

        result = self.env['aps.resources'].toggle_resource_completion(self.resource.id)
        self.assertEqual(result['newProgress'], 100.0)
        self.assertEqual(result['manualProgress'], 100.0)

    def test_response_rows_count_distinct_questions(self):
        self._answer(self.questions[0])
        self._answer(self.questions[0])
        progress = self._progress()
        self.assertEqual(progress['quizAnsweredQuestionCount'], 1)
        self.assertEqual(progress['quizProgress'], 25.0)

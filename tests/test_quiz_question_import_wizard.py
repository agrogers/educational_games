from odoo.tests.common import TransactionCase


class TestQuizQuestionImportWizard(TransactionCase):

    def test_import_handles_plain_text_markdown_in_odoo_editor_html(self):
        wizard = self.env['quiz.question.import.wizard'].create({
            'bulk_text': (
                '<div contenteditable="true" class="note-editable odoo-editor-editable" '
                'dir="ltr" spellcheck="true">'
                '<div class="o-paragraph">'
                '*Which of the following describes the biological importance '
                'of photosynthesis in terms of energy conversion?* (p135)'
                '</div>'
                '<div class="o-paragraph">A: Converting chemical energy into light energy</div>'
                '<div class="o-paragraph">B: **Converting light energy into chemical energy**</div>'
                '<div class="o-paragraph">C: Converting thermal energy into kinetic energy</div>'
                '<div class="o-paragraph o-we-hint" placeholder="Type &quot;/&quot; for commands">'
                '<br/></div>'
                '</div>'
            ),
        })

        wizard.action_import_questions()

        questions = self.env['quiz.question'].search([
            ('import_group', '=', wizard.import_group),
        ])
        self.assertEqual(len(questions), 1)

        question = questions[0]
        self.assertEqual(
            question.question_text,
            'Which of the following describes the biological importance '
            'of photosynthesis in terms of energy conversion? (p135)',
        )

        answers = question.answer_ids.sorted('sequence')
        self.assertEqual(len(answers), 3)
        self.assertFalse(answers[0].is_correct)
        self.assertTrue(answers[1].is_correct)
        self.assertFalse(answers[2].is_correct)

    def test_import_handles_mixed_italic_question_with_br_separated_answers(self):
        wizard = self.env['quiz.question.import.wizard'].create({
            'bulk_text': (
                '<p><em>Which of the following describes the biological importance '
                'of photosynthesis in terms of energy conversion?</em> (p135)<br/>'
                'A: Converting chemical energy into light energy<br/>'
                'B: <strong>Converting light energy into chemical energy</strong><br/>'
                'C: Converting thermal energy into kinetic energy</p>'
            ),
        })

        action = wizard.action_import_questions()

        self.assertEqual(action['res_model'], 'quiz.question')
        questions = self.env['quiz.question'].search([
            ('import_group', '=', wizard.import_group),
        ])
        self.assertEqual(len(questions), 1)

        question = questions[0]
        self.assertEqual(
            question.question_text,
            'Which of the following describes the biological importance '
            'of photosynthesis in terms of energy conversion? (p135)',
        )
        self.assertEqual(len(question.answer_ids), 3)

        answers = question.answer_ids.sorted('sequence')
        self.assertEqual(answers[0].answer_text, 'Converting chemical energy into light energy')
        self.assertFalse(answers[0].is_correct)
        self.assertEqual(answers[1].answer_text, 'Converting light energy into chemical energy')
        self.assertTrue(answers[1].is_correct)
        self.assertEqual(answers[2].answer_text, 'Converting thermal energy into kinetic energy')
        self.assertFalse(answers[2].is_correct)

    def test_default_import_group_is_next_highest_group(self):
        self.env['quiz.question'].create({
            'question_text': 'Existing question',
            'import_group': 27,
        })

        wizard = self.env['quiz.question.import.wizard'].new({})

        self.assertEqual(wizard.import_group, 28)
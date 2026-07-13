from odoo import models, fields, api
from odoo.exceptions import UserError
import re
import uuid


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    image_content = fields.Html(
        string='Image Content',
        help='Rich text content with an image for Memory Reveal quizzes. '
             'The first image found in this HTML will be used as the quiz image. '
             'Students will try to recall what is hidden behind blurred regions.',
    )
    image_url = fields.Char(
        string='Image URL',
        compute='_compute_image_url',
        store=True,
        help='URL to load the quiz image in the frontend.',
    )

    @api.depends('image_content')
    def _compute_image_url(self):
        for record in self:
            url = False
            if record.image_content:
                match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', record.image_content)
                if match:
                    url = match.group(1)
            record.image_url = url

    def action_open_memory_reveal_setup(self):
        """Launch the Memory Reveal teacher setup for this quiz."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before opening the setup.")
        if self.quiz_type != 'memory_reveal':
            raise UserError("This quiz is not a Memory Reveal quiz.")

        return {
            'type': 'ir.actions.client',
            'tag': 'action_memory_reveal_setup_js',
            'name': f"Memory Reveal Setup - {self.name}",
            'params': {'quiz_id': quiz_id},
            'context': {'default_quiz_id': quiz_id},
        }

    def action_preview_memory_reveal(self):
        """Launch the student Memory Reveal game for this quiz."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before previewing.")
        if self.quiz_type != 'memory_reveal':
            raise UserError("This quiz is not a Memory Reveal quiz.")

        quiz_params = {
            'quiz_id': quiz_id,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'action_memory_reveal_game_js',
            'name': self.name,
            'params': quiz_params,
            'context': quiz_params,
        }

    @api.model
    def submit_memory_reveal_assessment(self, quiz_id, question_id, answer_id, attempt_token=None):
        """
        Save a single Memory Reveal self-assessment response.

        Called by the student game each time they self-assess a revealed region.

        :param quiz_id: int
        :param question_id: int – the region (quiz.question)
        :param answer_id: int – the self-assessment answer selected
        :param attempt_token: str – groups responses from the same play session
        :returns: dict with marks_earned, total_score, total_possible
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")
        if quiz.quiz_type != 'memory_reveal':
            raise UserError("This method is only for Memory Reveal quizzes.")

        question = self.env['quiz.question'].browse(int(question_id))
        answer = self.env['quiz.answer'].browse(int(answer_id))
        if not question.exists() or not answer.exists():
            raise UserError("Invalid question or answer.")
        if answer.question_id != question:
            raise UserError("Answer does not belong to this question.")

        token = attempt_token or uuid.uuid4().hex

        # Upsert: if the student already assessed this region in this attempt, update it
        existing = self.env['quiz.response'].sudo().search([
            ('quiz_id', '=', quiz.id),
            ('question_id', '=', question.id),
            ('user_id', '=', self.env.user.id),
            ('attempt_token', '=', token),
        ], limit=1)

        if existing:
            existing.write({
                'answer_id': answer.id,
                'is_correct': answer.is_correct,
            })
        else:
            self.env['quiz.response'].sudo().create({
                'quiz_id': quiz.id,
                'question_id': question.id,
                'answer_id': answer.id,
                'user_id': self.env.user.id,
                'attempt_token': token,
                'is_correct': answer.is_correct,
            })

        # Compute running score for this attempt
        responses = self.env['quiz.response'].sudo().search([
            ('quiz_id', '=', quiz.id),
            ('user_id', '=', self.env.user.id),
            ('attempt_token', '=', token),
        ])
        total_score = sum(r.answer_id.marks for r in responses)
        total_possible = len(quiz.question_ids) * 2  # 2 marks per region (strong correct)

        return {
            'marks_earned': answer.marks,
            'total_score': total_score,
            'total_possible': total_possible,
            'attempt_token': token,
        }
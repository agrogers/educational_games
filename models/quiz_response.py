from odoo import models, fields


class QuizResponse(models.Model):
    """
    Records each answer a student selects when submitting a quiz.

    One record is created per selected answer per submission, so a student who
    picks three options for a multi-answer question produces three rows.
    ``is_correct`` reflects whether that specific answer option is a correct
    one (copied from ``quiz.answer.is_correct`` at submission time).
    """
    _name = 'quiz.response'
    _description = 'Quiz Question Response'
    _order = 'create_date desc, id desc'

    quiz_id = fields.Many2one(
        'quiz.quiz', string='Quiz', required=True, ondelete='cascade', index=True,
    )
    question_id = fields.Many2one(
        'quiz.question', string='Question', required=True, ondelete='cascade', index=True,
    )
    answer_id = fields.Many2one(
        'quiz.answer', string='Selected Answer', required=True, ondelete='cascade',
    )
    user_id = fields.Many2one(
        'res.users', string='Student', required=True,
        default=lambda self: self.env.user, index=True,
    )
    attempt_token = fields.Char(
        string='Attempt Token',
        index=True,
        copy=False,
        help='Groups all selected answers that belong to the same question attempt.',
    )
    is_correct = fields.Boolean(
        string='Correct Answer',
        help='Whether the selected answer option is a correct answer.',
    )

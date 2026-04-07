from odoo import models, fields


class QuizAnswer(models.Model):
    _name = 'quiz.answer'
    _description = 'Quiz Answer'
    _order = 'question_id, sequence, id'

    question_id = fields.Many2one('quiz.question', string='Question', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    answer_text = fields.Html(string='Answer Option', required=True, sanitize=True)
    is_correct = fields.Boolean(string='Correct Answer', default=False)
    select_count = fields.Integer(
        string='Times Selected',
        default=0,
        readonly=True,
        help='Total number of times this answer option has been selected by students.',
    )
    select_pct_all = fields.Float(
        string='% Selected (All)',
        digits=(5, 1),
        default=0.0,
        readonly=True,
        help='Percentage of all question attempts where this option was selected.',
    )
    select_pct_recent = fields.Float(
        string='% Selected (1h)',
        digits=(5, 1),
        default=0.0,
        readonly=True,
        help='Percentage of question attempts in the last hour where this option was selected.',
    )

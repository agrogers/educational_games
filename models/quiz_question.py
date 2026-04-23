from collections import defaultdict
from datetime import timedelta
from odoo import models, fields, api


class QuizQuestion(models.Model):
    _name = 'quiz.question'
    _description = 'Quiz Question'
    _order = 'quiz_id, sequence, id'

    quiz_id = fields.Many2one('quiz.quiz', string='Primary Quiz', ondelete='set null')
    all_quiz_ids = fields.Many2many(
        'quiz.quiz',
        'quiz_quiz_question_rel',
        'question_id',
        'quiz_id',
        string='Quizzes',
        help='All quizzes this question belongs to.',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    question_text = fields.Html(string='Question', required=True, sanitize=True)
    marks = fields.Integer(string='Marks', default=1)
    allow_multiple = fields.Boolean(
        string='Allow Multiple Answers',
        default=False,
        help='If checked, students can select more than one answer.',
    )
    answer_ids = fields.One2many('quiz.answer', 'question_id', string='Answers')
    correct_answer = fields.Html(
        string='Correct Answer',
        compute='_compute_correct_answer',
        store=True,
        readonly=True,
        sanitize=True,
        help='Stored text of the correct answer option(s).',
    )
    tag_ids = fields.Many2many(
        'quiz.tag',
        'quiz_question_tag_rel',
        'question_id',
        'tag_id',
        string='Tags',
    )
    subject_ids = fields.Many2many(
        'aps.subject',
        'educational_games_question_subject_rel',
        'question_id',
        'subject_id',
        string='Subjects',
    )
    import_group = fields.Integer(
        string='Import Group',
        help='Optional grouping ID used to identify questions imported together.',
    )
    correct_answer_count = fields.Integer(
        string='Correct Answers',
        compute='_compute_correct_answer_count',
        store=True,
    )
    attempt_count = fields.Integer(
        string='Attempts',
        default=0,
        readonly=True,
        help='Total number of answer selections recorded for this question.',
    )
    pct_correct_all = fields.Float(
        string='% Correct (All)',
        digits=(5, 1),
        default=0.0,
        readonly=True,
        help='Percentage of all recorded answer selections that were correct.',
    )
    pct_correct_recent = fields.Float(
        string='% Correct (1h)',
        digits=(5, 1),
        default=0.0,
        readonly=True,
        help='Percentage of answer selections in the last hour that were correct.',
    )

    @api.depends('answer_ids.is_correct')
    def _compute_correct_answer_count(self):
        for record in self:
            record.correct_answer_count = sum(1 for a in record.answer_ids if a.is_correct)

    @api.depends('answer_ids.is_correct', 'answer_ids.answer_text', 'answer_ids.sequence')
    def _compute_correct_answer(self):
        for record in self:
            correct_answers = record.answer_ids.filtered('is_correct').sorted('sequence')
            if not correct_answers:
                record.correct_answer = False
            elif len(correct_answers) == 1:
                record.correct_answer = correct_answers.answer_text
            else:
                record.correct_answer = '<br/>'.join(a.answer_text or '' for a in correct_answers)

    @api.model
    def _recompute_stats(self, question_ids):
        """Recompute stored response statistics for the given question IDs.

        Updates attempt_count / pct_correct_all / pct_correct_recent on
        quiz.question and select_count / select_pct_all / select_pct_recent
        on every quiz.answer belonging to those questions.
        """
        if not question_ids:
            return

        cutoff = fields.Datetime.now() - timedelta(hours=1)
        Response = self.env['quiz.response'].sudo()

        def _aggregate(domain):
            """Return {question_id: {answer_id: [total, correct]}} from read_group."""
            rows = Response.read_group(
                domain=domain,
                fields=['question_id', 'answer_id', 'is_correct'],
                groupby=['question_id', 'answer_id', 'is_correct'],
                lazy=False,
            )
            result = defaultdict(lambda: defaultdict(lambda: [0, 0]))
            for row in rows:
                if not row.get('question_id') or not row.get('answer_id'):
                    continue
                qid = row['question_id'][0]
                aid = row['answer_id'][0]
                count = row['__count']
                result[qid][aid][0] += count
                if row['is_correct']:
                    result[qid][aid][1] += count
            return result

        all_stats = _aggregate([('question_id', 'in', question_ids)])
        recent_stats = _aggregate([
            ('question_id', 'in', question_ids),
            ('create_date', '>=', cutoff),
        ])

        for question in self.browse(question_ids):
            q_all = all_stats.get(question.id, {})
            q_rec = recent_stats.get(question.id, {})

            q_total_all = sum(v[0] for v in q_all.values())
            q_correct_all = sum(v[1] for v in q_all.values())
            q_total_rec = sum(v[0] for v in q_rec.values())
            q_correct_rec = sum(v[1] for v in q_rec.values())

            question.attempt_count = q_total_all
            question.pct_correct_all = (
                round(q_correct_all / q_total_all * 100, 1) if q_total_all else 0.0
            )
            question.pct_correct_recent = (
                round(q_correct_rec / q_total_rec * 100, 1) if q_total_rec else 0.0
            )

            for answer in question.answer_ids:
                a_all = q_all.get(answer.id, [0, 0])
                a_rec = q_rec.get(answer.id, [0, 0])
                answer.select_count = a_all[0]
                answer.select_pct_all = (
                    round(a_all[0] / q_total_all * 100, 1) if q_total_all else 0.0
                )
                answer.select_pct_recent = (
                    round(a_rec[0] / q_total_rec * 100, 1) if q_total_rec else 0.0
                )

    def action_open_tag_wizard(self):
        """Open the bulk modify wizard for selected questions."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'quiz.question.tag.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'default_question_ids': [(6, 0, self.ids)],
            },
        }

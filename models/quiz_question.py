from collections import defaultdict
from datetime import timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError


class QuizQuestion(models.Model):
    _name = 'quiz.question'
    _description = 'Quiz Question'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    response_ids = fields.One2many('quiz.response', 'question_id', string='Responses')
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
    region_x1 = fields.Float(
        string='Region Left (%)',
        default=0.0,
        help='Left edge of the blur region as a percentage of image width (0-100).',
    )
    region_y1 = fields.Float(
        string='Region Top (%)',
        default=0.0,
        help='Top edge of the blur region as a percentage of image height (0-100).',
    )
    region_x2 = fields.Float(
        string='Region Right (%)',
        default=0.0,
        help='Right edge of the blur region as a percentage of image width (0-100).',
    )
    region_y2 = fields.Float(
        string='Region Bottom (%)',
        default=0.0,
        help='Bottom edge of the blur region as a percentage of image height (0-100).',
    )
    correct_answer_count = fields.Integer(
        string='Correct Answers',
        compute='_compute_correct_answer_count',
        store=True,
    )
    attempt_count = fields.Integer(
        string='Attempts',
        compute='_compute_attempt_stats',
        store=True,
        readonly=True,
        help='Total number of answer selections recorded for this question.',
    )
    pct_correct_all = fields.Float(
        string='% Correct (All)',
        digits=(5, 1),
        compute='_compute_attempt_stats',
        store=True,
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

    @api.depends('response_ids.is_correct')
    def _compute_attempt_stats(self):
        for question in self:
            total = len(question.response_ids)
            correct = sum(1 for r in question.response_ids if r.is_correct)
            question.attempt_count = total
            question.pct_correct_all = round(correct / total * 100, 1) if total else 0.0

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

    def action_merge_questions(self):
        """Merge two or more selected questions into one.

        Keeps the first selected question, disposes of the others, and
        transfers their incorrect answers, responses, tags, and quiz
        memberships to the kept question.
        """
        if len(self) < 2:
            raise UserError('Please select at least two questions to merge.')

        questions = self
        keep = questions[:1]
        dispose = questions[1:]

        # Collect tags and quizzes from disposed questions to merge
        all_tags = keep.tag_ids | dispose.mapped('tag_ids')
        all_quizzes = keep.all_quiz_ids | dispose.mapped('all_quiz_ids')

        # Move incorrect answers from disposed questions to kept question.
        # Correct answers from disposed questions are discarded — the kept
        # question already has its own correct answer(s).
        incorrect_answers = self.env['quiz.answer'].search([
            ('question_id', 'in', dispose.ids),
            ('is_correct', '=', False),
        ])
        if incorrect_answers:
            incorrect_answers.write({'question_id': keep.id})

        # Re-point responses that selected a disposed correct answer to the
        # kept question's correct answer, so student scores are preserved.
        disposed_correct = self.env['quiz.answer'].search([
            ('question_id', 'in', dispose.ids),
            ('is_correct', '=', True),
        ])
        kept_correct = keep.answer_ids.filtered('is_correct')
        if disposed_correct and kept_correct:
            # Use the first correct answer on the kept question as the target.
            target_answer = kept_correct[:1]
            resp_to_remap = self.env['quiz.response'].search([
                ('answer_id', 'in', disposed_correct.ids),
            ])
            if resp_to_remap:
                resp_to_remap.write({'answer_id': target_answer.id})

        # Move remaining responses from disposed questions to kept question.
        # These point to incorrect answers (already moved) or to correct
        # answers that no longer exist (already remapped above).
        responses = self.env['quiz.response'].search([
            ('question_id', 'in', dispose.ids),
        ])
        if responses:
            responses.write({'question_id': keep.id})

        # Update kept question with merged tags and quizzes
        keep.write({
            'tag_ids': [(6, 0, all_tags.ids)],
            'all_quiz_ids': [(6, 0, all_quizzes.ids)],
        })

        # Delete disposed questions (their answers and responses are now
        # owned by the kept question, so they won't cascade-delete)
        dispose.unlink()

        # Recompute stats for the kept question
        keep._recompute_stats([keep.id])

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Questions Merged',
                'message': (
                    f'Kept "{keep.display_name or keep.id}". '
                    f'Merged {len(dispose)} question(s), '
                    f'{len(incorrect_answers)} answer(s), '
                    f'and {len(responses)} response(s).'
                ),
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def action_open_import_wizard(self):
        """Open the question import wizard."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Quiz Questions',
            'res_model': 'quiz.question.import.wizard',
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def ensure_memory_reveal_answers(self, question_id):
        """Ensure the 3 traffic-light self-assessment answers exist for a
        Memory Reveal region/question.  Creates them if missing.

        Returns a dict mapping marks → answer id, e.g. ``{2: id, 1: id, 0: id}``.
        """
        question = self.browse(int(question_id))
        if not question.exists():
            return {"error": "Question not found"}

        existing = {a.marks: a for a in question.answer_ids}

        traffic_light_answers = [
            {
                "marks": 2,
                "answer_text": "Correct (Easy) – I knew it!",
                "is_correct": True,
                "sequence": 3,
            },
            {
                "marks": 1,
                "answer_text": "Correct (Hard) – I got it with difficulty",
                "is_correct": True,
                "sequence": 2,
            },
            {
                "marks": 0,
                "answer_text": "Incorrect – I did not know it",
                "is_correct": False,
                "sequence": 1,
            },
        ]

        result = {}
        for cfg in traffic_light_answers:
            if cfg["marks"] in existing:
                result[cfg["marks"]] = existing[cfg["marks"]].id
            else:
                answer = self.env["quiz.answer"].create({
                    "question_id": question.id,
                    "answer_text": cfg["answer_text"],
                    "is_correct": cfg["is_correct"],
                    "marks": cfg["marks"],
                    "sequence": cfg["sequence"],
                })
                result[cfg["marks"]] = answer.id

        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._resync_quizzes_that_include_us()
        # Auto-create default self-assessment answers for memory_reveal questions
        for rec in records:
            if rec.quiz_id and rec.quiz_id.quiz_type == 'memory_reveal' and not rec.answer_ids:
                rec._create_memory_reveal_default_answers()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'all_quiz_ids' in vals:
            self._resync_quizzes_that_include_us()
        return result

    def _create_memory_reveal_default_answers(self):
        """Create the three default self-assessment answers for a memory_reveal question."""
        Answer = self.env['quiz.answer']
        defaults = [
            {'sequence': 1, 'answer_text': 'Strong Correct', 'is_correct': True, 'marks': 2},
            {'sequence': 2, 'answer_text': 'Correct with Difficulty', 'is_correct': True, 'marks': 1},
            {'sequence': 3, 'answer_text': 'Incorrect', 'is_correct': False, 'marks': 0},
        ]
        for vals in defaults:
            vals['question_id'] = self.id
        Answer.create(defaults)

    def unlink(self):
        # Before deletion, find which quizzes need re-syncing
        affected_quiz_ids = self.mapped('all_quiz_ids').ids
        result = super().unlink()
        if affected_quiz_ids:
            including = self.env['quiz.quiz'].search(
                [('include_other_quizzes', 'in', affected_quiz_ids)]
            )
            if including:
                including._sync_inherited_questions()
        return result

    def _resync_quizzes_that_include_us(self):
        """Re-sync any quiz that *includes* a quiz these questions belong to."""
        direct_quiz_ids = self.mapped('all_quiz_ids').ids
        if not direct_quiz_ids:
            return
        including = self.env['quiz.quiz'].search(
            [('include_other_quizzes', 'in', direct_quiz_ids)]
        )
        if including:
            including._sync_inherited_questions()

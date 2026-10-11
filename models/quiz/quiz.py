from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import config
import base64
from collections import Counter
from datetime import timedelta
import hashlib
import hmac
import json
import random
import re
import uuid


# Hardcoded bypass: set to True to skip HMAC signature verification on quiz
# tokens. Useful when database.secret changed and existing links must keep
# working. Set back to False once tokens have been regenerated.
SKIP_QUIZ_TOKEN_SIGNATURE_CHECK = True

class Quiz(models.Model):
    _name = 'quiz.quiz'
    _description = 'Quiz'
    _order = 'name'

    name = fields.Char(string='Quiz Name', required=True)
    quiz_type = fields.Selection(
        [
            ('standard', 'Standard Quiz'),
            ('memory_reveal', 'Memory Reveal'),
        ],
        string='Quiz Type',
        default='standard',
        required=True,
        help='Standard Quiz: traditional question-and-answer format. '
             'Memory Reveal: students self-assess memory of concealed image regions.',
    )
    subject_ids = fields.Many2many(
        'aps.subject',
        'educational_games_quiz_subject_rel',
        'quiz_id',
        'subject_id',
        string='Subjects',
    )
    description = fields.Html(string='Description')
    question_ids = fields.Many2many(
        'quiz.question',
        'quiz_quiz_question_rel',
        'quiz_id',
        'question_id',
        string='Questions',
    )
    include_other_quizzes = fields.Many2many(
        'quiz.quiz',
        'quiz_quiz_include_rel',
        'quiz_id',
        'included_quiz_id',
        string='Include Questions From',
        help=(
            'Questions from these quizzes are automatically included when playing this quiz. '
            'Use this to build composite quizzes that inherit questions from other quizzes.'
        ),
    )
    inherited_question_ids = fields.Many2many(
        'quiz.question',
        'quiz_inherited_question_rel',
        'quiz_id',
        'question_id',
        string='Inherited Questions',
        help='Questions automatically pulled in from included quizzes. Managed automatically — do not edit manually.',
    )
    manual_question_ids = fields.Many2many(
        'quiz.question',
        'quiz_manual_question_rel',
        'quiz_id',
        'question_id',
        string='Manual Questions',
        help='Internal tracking of questions linked directly to this quiz.',
    )
    question_count = fields.Integer(
        string='Number of Questions',
        compute='_compute_question_count',
        store=False,
    )
    total_marks = fields.Integer(
        string='Total Marks',
        compute='_compute_total_marks',
        store=False,
    )
    header_image = fields.Image(
        string='Header Image',
        max_width=1400,
        max_height=300,
        help='Optional banner image displayed in the quiz header.',
    )
    display_question_count = fields.Integer(
        string='Questions to Show',
        default=10,
        help='Number of questions to display to the student. 0 = show all questions.',
    )
    display_option_count = fields.Integer(
        string='Options to Show',
        default=4,
        help=(
            'Number of answer options to show per question. '
            'The correct answer is always included; remaining slots are filled randomly. '
            '0 = show all options.'
        ),
    )
    allow_resubmission = fields.Boolean(
        string='Allow Resubmission',
        default=True,
        help=(
            'If enabled, students can retake the quiz and save each attempt as '
            'a new submission. The "Submit Quiz" button changes to '
            '"Resubmit this Quiz" on retakes. '
            'If disabled, retakes run in practice mode only (no save).'
        ),
    )
    filter_tag_ids = fields.Many2many(
        'quiz.tag',
        'quiz_quiz_filter_tag_rel',
        'quiz_id',
        'tag_id',
        string='Filter by Tags',
        help=(
            'Limit questions to those that have at least one of these tags. '
            'Leave empty to include all questions regardless of tag.'
        ),
    )
    filter_exclude_tag_ids = fields.Many2many(
        'quiz.tag',
        'quiz_quiz_filter_exclude_tag_rel',
        'quiz_id',
        'tag_id',
        string='Exclude Questions With Tags',
        help='Exclude questions that have at least one of these tags.',
    )
    filter_subject_ids = fields.Many2many(
        'aps.subject',
        'educational_games_quiz_filter_subject_rel',
        'quiz_id',
        'subject_id',
        string='Filter by Subjects',
        help='Limit questions to those linked to at least one of these subjects.',
    )
    filter_min_attempts = fields.Char(
        string='Min Attempts',
        help='Only include questions attempted at least this many times overall.',
    )
    filter_max_attempts = fields.Char(
        string='Max Attempts',
        help='Only include questions attempted no more than this many times overall.',
    )
    filter_max_pct_correct = fields.Char(
        string='Max % Correct',
        help='Only include questions whose overall % correct is at or below this value. Use this to focuse on questions the whole class is having difficulties with.',
        default=80,
    )
    filter_student_weighted_score_pct = fields.Char(
        string="Student's Weighted Score %",
        help=(
            'Exclude a question when the student has reached at least this weighted score percentage. '
            'Most recent attempt has weight 1, next 1/2, next 1/3, and so on.'
        ),
    )
    filter_student_attempts = fields.Char(
        string="Student's Attempts",
        help='Only consider excluding a question when the student has attempted it at least this many times.',
        default=2,

    )
    filter_exclude_answered_days = fields.Char(
        string='Exclude Answered In Previous Days',
        help='Exclude questions the current student answered within the previous X days.',
    )
    filter_summary_preview = fields.Text(
        string='Filter',
        compute='_compute_filter_summary_preview',
        readonly=True,
    )
    bulk_add_question_ids_text = fields.Text(
        string='Question IDs',
        help='Paste question IDs separated by commas and/or whitespace.',
    )
    bulk_add_question_ids = fields.Many2many(
        'quiz.question',
        'educational_games_quiz_bulk_add_question_rel',
        'quiz_id',
        'question_id',
        string='Questions to Add',
        help='Staged questions found by the Check button before adding to this quiz.',
    )
    quiz_url_params = fields.Char(
        string='APEX Game URL',
        compute='_compute_quiz_url_params',
        help=(
            'Copy this into APEX to open this specific quiz. '
            'Format: action:<id>?quiz_id=<id>&…  '
            'Paste it into the resource URL field in the APEX module.'
        ),
    )
    @api.depends(
        'question_ids',
        'question_ids.tag_ids',
        'question_ids.subject_ids',
        'inherited_question_ids',
        'include_other_quizzes',
        'filter_exclude_tag_ids',
        'filter_subject_ids',
    )
    def _compute_question_count(self):
        for record in self:
            questions = record._filtered_questions()
            record.question_count = len(questions)

    @api.depends(
        'question_ids.marks',
        'question_ids.tag_ids',
        'question_ids.subject_ids',
        'inherited_question_ids',
        'include_other_quizzes',
        'filter_exclude_tag_ids',
        'filter_subject_ids',
    )
    def _compute_total_marks(self):
        for record in self:
            questions = record._filtered_questions()
            record.total_marks = sum(q.marks for q in questions)

    def _filtered_questions(self):
        """Return question_ids filtered by filter_tag_ids and filter_subject_ids."""
        questions = self.question_ids
        if self.filter_tag_ids:
            tag_ids = set(self.filter_tag_ids.ids)
            questions = questions.filtered(lambda q: tag_ids.intersection(q.tag_ids.ids))
        if self.filter_exclude_tag_ids:
            excluded_tag_ids = set(self.filter_exclude_tag_ids.ids)
            questions = questions.filtered(
                lambda q: not excluded_tag_ids.intersection(q.tag_ids.ids)
            )
        if self.filter_subject_ids:
            subject_ids = set(self.filter_subject_ids.ids)
            questions = questions.filtered(lambda q: subject_ids.intersection(q.subject_ids.ids))
        return questions

    def write(self, vals):
        result = super().write(vals)
        if 'filter_tag_ids' in vals:
            including_quizzes = self.env['quiz.quiz'].search(
                [('include_other_quizzes', 'in', self.ids)]
            )
            if including_quizzes:
                including_quizzes.with_context(
                    skip_quiz_filter_sync=True,
                )._sync_inherited_questions()
        return result

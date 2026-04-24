from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError
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


class Quiz(models.Model):
    _name = 'quiz.quiz'
    _description = 'Quiz'
    _order = 'name'

    name = fields.Char(string='Quiz Name', required=True)
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
    question_count = fields.Integer(
        string='Number of Questions',
        compute='_compute_question_count',
        store=True,
    )
    total_marks = fields.Integer(
        string='Total Marks',
        compute='_compute_total_marks',
        store=True,
    )
    header_image = fields.Image(
        string='Header Image',
        max_width=1400,
        max_height=300,
        help='Optional banner image displayed in the quiz header.',
    )
    display_question_count = fields.Integer(
        string='Questions to Show',
        default=0,
        help='Number of questions to display to the student. 0 = show all questions.',
    )
    display_option_count = fields.Integer(
        string='Options to Show',
        default=0,
        help=(
            'Number of answer options to show per question. '
            'The correct answer is always included; remaining slots are filled randomly. '
            '0 = show all options.'
        ),
    )
    allow_resubmission = fields.Boolean(
        string='Allow Resubmission',
        default=False,
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
    @api.depends('question_ids')
    def _compute_question_count(self):
        for record in self:
            record.question_count = len(record.question_ids)

    @api.depends('question_ids.marks')
    def _compute_total_marks(self):
        for record in self:
            record.total_marks = sum(q.marks for q in record.question_ids)

    @staticmethod
    def _sanitize_nonnegative_int(value):
        if value in (False, None, ''):
            return 0
        return max(0, int(str(value).strip() or 0))

    def _get_quiz_filter_payload(self):
        return {
            'filter_tag_ids': sorted(self.filter_tag_ids.ids),
            'filter_subject_ids': sorted(self.filter_subject_ids.ids),
            'filter_min_attempts': self._sanitize_nonnegative_int(self.filter_min_attempts),
            'filter_max_attempts': self._sanitize_nonnegative_int(self.filter_max_attempts),
            'filter_max_pct_correct': self._sanitize_nonnegative_int(self.filter_max_pct_correct),
            'filter_student_weighted_score_pct': self._sanitize_nonnegative_int(self.filter_student_weighted_score_pct),
            'filter_student_attempts': self._sanitize_nonnegative_int(self.filter_student_attempts),
            'filter_exclude_answered_days': self._sanitize_nonnegative_int(self.filter_exclude_answered_days),
        }

    @classmethod
    def _normalize_quiz_filter_payload(cls, payload):
        payload = payload or {}
        return {
            'filter_tag_ids': sorted(int(tag_id) for tag_id in (payload.get('filter_tag_ids') or [])),
            'filter_subject_ids': sorted(int(subject_id) for subject_id in (payload.get('filter_subject_ids') or [])),
            'filter_min_attempts': cls._sanitize_nonnegative_int(payload.get('filter_min_attempts')),
            'filter_max_attempts': cls._sanitize_nonnegative_int(payload.get('filter_max_attempts')),
            'filter_max_pct_correct': cls._sanitize_nonnegative_int(payload.get('filter_max_pct_correct')),
            'filter_student_weighted_score_pct': cls._sanitize_nonnegative_int(payload.get('filter_student_weighted_score_pct')),
            'filter_student_attempts': cls._sanitize_nonnegative_int(payload.get('filter_student_attempts')),
            'filter_exclude_answered_days': cls._sanitize_nonnegative_int(payload.get('filter_exclude_answered_days')),
        }

    def _build_filter_summary(self, filter_payload):
        filter_payload = self._normalize_quiz_filter_payload(filter_payload)
        parts = []

        if filter_payload['filter_tag_ids']:
            tags = self.env['quiz.tag'].sudo().browse(filter_payload['filter_tag_ids']).exists().mapped('name')
            parts.append(f"Tags: {', '.join(tags)}")
        if filter_payload['filter_subject_ids']:
            subjects = self.env['aps.subject'].sudo().browse(filter_payload['filter_subject_ids']).exists().mapped('name')
            parts.append(f"Subjects: {', '.join(subjects)}")

        min_attempts = filter_payload['filter_min_attempts']
        max_attempts = filter_payload['filter_max_attempts']
        if min_attempts and max_attempts:
            parts.append(f"Attempts between {min_attempts} and {max_attempts}")
        elif min_attempts:
            parts.append(f"Attempts at least {min_attempts}")
        elif max_attempts:
            parts.append(f"Attempts at most {max_attempts}")

        if filter_payload['filter_max_pct_correct']:
            parts.append(f"Overall % correct at most {filter_payload['filter_max_pct_correct']}%")

        student_attempts = filter_payload['filter_student_attempts']
        student_weighted = filter_payload['filter_student_weighted_score_pct']
        exclude_answered_days = filter_payload['filter_exclude_answered_days']
        student_exclusion_parts = []
        if student_attempts:
            student_exclusion_parts.append(f"your attempts are at least {student_attempts}")
        if student_weighted:
            student_exclusion_parts.append(f"your weighted score is at least {student_weighted}%")
        if exclude_answered_days:
            student_exclusion_parts.append(f"you answered it in the previous {exclude_answered_days} days")

        if student_exclusion_parts:
            parts.append(f"Exclude if all of these are true: {' and '.join(student_exclusion_parts)}")

        return 'Active filters: ' + ' | '.join(parts) if parts else ''

    @api.depends(
        'filter_tag_ids',
        'filter_subject_ids',
        'filter_min_attempts',
        'filter_max_attempts',
        'filter_max_pct_correct',
        'filter_student_weighted_score_pct',
        'filter_student_attempts',
        'filter_exclude_answered_days',
    )
    def _compute_filter_summary_preview(self):
        for record in self:
            record.filter_summary_preview = record._build_filter_summary(record._get_quiz_filter_payload())

    @staticmethod
    def _response_attempt_group_key(response):
        if response.attempt_token:
            return response.attempt_token
        if response.create_date:
            return f"legacy:{fields.Datetime.to_string(response.create_date)[:19]}"
        return f"legacy-id:{response.id}"

    def _get_student_question_attempt_stats(self, questions, user=None):
        user = user or self.env.user
        if not questions:
            return {}

        responses = self.env['quiz.response'].sudo().search(
            [('question_id', 'in', questions.ids), ('user_id', '=', user.id)],
            order='create_date desc, id desc',
        )

        grouped = {}
        for response in responses:
            question_groups = grouped.setdefault(response.question_id.id, {})
            group_key = self._response_attempt_group_key(response)
            group = question_groups.setdefault(group_key, {'selected_ids': set(), 'answered_at': response.create_date})
            group['selected_ids'].add(response.answer_id.id)
            if response.create_date and (
                not group['answered_at'] or response.create_date > group['answered_at']
            ):
                group['answered_at'] = response.create_date

        stats = {}
        for question in questions:
            attempts = list(grouped.get(question.id, {}).values())
            correct_ids = set(question.answer_ids.filtered('is_correct').ids)
            weighted_total = 0.0
            weight_sum = 0.0

            for index, attempt in enumerate(attempts, start=1):
                weight = 1.0 / index
                attempt_score = 100.0 if correct_ids and attempt['selected_ids'] == correct_ids else 0.0
                weighted_total += attempt_score * weight
                weight_sum += weight

            stats[question.id] = {
                'attempt_count': len(attempts),
                'weighted_score_pct': round(weighted_total / weight_sum, 1) if weight_sum else None,
                'last_answered_at': attempts[0]['answered_at'] if attempts else None,
            }

        return stats

    def _question_matches_filter_payload(self, question, filter_payload, student_stats=None):
        filter_payload = self._normalize_quiz_filter_payload(filter_payload)
        student_stats = student_stats or {}

        if filter_payload['filter_tag_ids']:
            if not set(filter_payload['filter_tag_ids']).intersection(question.tag_ids.ids):
                return False

        if filter_payload['filter_subject_ids']:
            if not set(filter_payload['filter_subject_ids']).intersection(question.subject_ids.ids):
                return False

        min_attempts = filter_payload['filter_min_attempts']
        if min_attempts and question.attempt_count < min_attempts:
            return False

        max_attempts = filter_payload['filter_max_attempts']
        if max_attempts and question.attempt_count > max_attempts:
            return False

        max_pct_correct = filter_payload['filter_max_pct_correct']
        if max_pct_correct and question.pct_correct_all > max_pct_correct:
            return False

        student_attempt_threshold = filter_payload['filter_student_attempts']
        student_weighted_threshold = filter_payload['filter_student_weighted_score_pct']
        exclude_answered_days = filter_payload['filter_exclude_answered_days']
        if student_attempt_threshold or student_weighted_threshold or exclude_answered_days:
            question_stats = student_stats.get(
                question.id,
                {'attempt_count': 0, 'weighted_score_pct': None, 'last_answered_at': None},
            )
            meets_attempt_threshold = (
                question_stats['attempt_count'] >= student_attempt_threshold
                if student_attempt_threshold else True
            )
            weighted_score = question_stats['weighted_score_pct']
            meets_weighted_threshold = (
                weighted_score is not None and weighted_score >= student_weighted_threshold
                if student_weighted_threshold else True
            )
            last_answered_at = question_stats['last_answered_at']
            meets_recent_answer_threshold = True
            if exclude_answered_days:
                meets_recent_answer_threshold = False
                if last_answered_at:
                    cutoff = fields.Datetime.now() - timedelta(days=exclude_answered_days)
                    meets_recent_answer_threshold = last_answered_at >= cutoff

            if meets_attempt_threshold and meets_weighted_threshold and meets_recent_answer_threshold:
                return False

        return True

    @staticmethod
    def _b64url_encode(data):
        return base64.urlsafe_b64encode(data).decode().rstrip('=')

    @staticmethod
    def _b64url_decode(data):
        pad = '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + pad).encode())

    def _sign_quiz_payload(self, payload_json):
        secret = (config.get('database.secret') or self.env.cr.dbname or 'odoo').encode()
        return hmac.new(secret, payload_json.encode(), hashlib.sha256).digest()

    def _build_quiz_token(self, quiz_id, question_count=0, option_count=0, allow_resubmission=False, filter_payload=None):
        payload = {
            'quiz_id': int(quiz_id),
            'question_count': max(0, int(question_count or 0)),
            'option_count': max(0, int(option_count or 0)),
            'allow_resubmission': bool(allow_resubmission),
        }
        payload.update(self._normalize_quiz_filter_payload(filter_payload))
        payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        signature = self._sign_quiz_payload(payload_json)
        return f"{self._b64url_encode(payload_json.encode())}.{self._b64url_encode(signature)}"

    def _decode_quiz_token(self, token):
        if not token or '.' not in token:
            return None
        payload_part, sig_part = token.split('.', 1)
        try:
            payload_json = self._b64url_decode(payload_part).decode()
            signature = self._b64url_decode(sig_part)
            expected = self._sign_quiz_payload(payload_json)
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(payload_json)
            filter_payload = self._normalize_quiz_filter_payload(payload)
            return {
                'quiz_id': int(payload.get('quiz_id') or 0),
                'question_count': max(0, int(payload.get('question_count') or 0)),
                'option_count': max(0, int(payload.get('option_count') or 0)),
                'allow_resubmission': bool(payload.get('allow_resubmission')),
                **filter_payload,
            }
        except Exception:
            return None

    @api.depends(
        'display_question_count',
        'display_option_count',
        'allow_resubmission',
        'filter_tag_ids',
        'filter_subject_ids',
        'filter_min_attempts',
        'filter_max_attempts',
        'filter_max_pct_correct',
        'filter_student_weighted_score_pct',
        'filter_student_attempts',
        'filter_exclude_answered_days',
    )
    def _compute_quiz_url_params(self):
        # Resolve the client action ID once for all records in this batch.
        # The format APEX expects is: action:<action_id>?quiz_id=<quiz_id>&quiz_token=<signed>
        try:
            action = self.env.ref('educational_games.action_quiz_game')
            action_id = action.id
        except ValueError:
            # External ID not found — log a warning so it is easy to diagnose
            import logging
            logging.getLogger(__name__).warning(
                "educational_games.action_quiz_game not found; quiz URL will not contain a valid action ID."
            )
            action_id = 'UNKNOWN'

        for record in self:
            # During onchange on unsaved forms, record.id is a NewId placeholder.
            # Only generate a signed URL once we have a real persisted quiz ID.
            quiz_id = record._origin.id or (record.id if isinstance(record.id, int) else 0)
            if not quiz_id:
                record.quiz_url_params = ''
                continue

            token = record._build_quiz_token(
                quiz_id,
                record.display_question_count,
                record.display_option_count,
                record.allow_resubmission,
                record._get_quiz_filter_payload(),
            )
            parts = [f'quiz_id={quiz_id}', f'quiz_token={token}']
            record.quiz_url_params = f'action:{action_id}?{"&".join(parts)}'

    def action_preview_quiz(self):
        """Launch the student quiz view in preview/practice mode."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before previewing.")

        # Use a signed token so URL params can configure quiz difficulty without
        # exposing editable plain counts in the browser address bar.
        quiz_params = {
            'quiz_id': quiz_id,
            'quiz_token': self._build_quiz_token(
                quiz_id,
                self.display_question_count,
                self.display_option_count,
                self.allow_resubmission,
                self._get_quiz_filter_payload(),
            ),
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'action_quiz_game_js',
            'name': self.name,
            # params are put into the URL by the Odoo 18 router, so the quiz
            # can be refreshed without losing the signed quiz context.
            'params': quiz_params,
            # context is kept for compatibility (some callers read it directly).
            'context': quiz_params,
        }

    def action_delete_all_questions(self):
        """Delete all questions (and their cascaded answers) for this quiz.

        Questions whose primary quiz (quiz_id) is this quiz are permanently
        deleted.  Questions shared from another primary quiz are only removed
        from this quiz's question_ids relation — they remain intact.
        """
        for record in self:
            owned = record.question_ids.filtered(lambda q: q.quiz_id == record)
            shared = record.question_ids - owned
            if shared:
                record.question_ids = [(3, q.id) for q in shared]
            owned.unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self[:1].id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_bulk_check_question_ids(self):
        self.ensure_one()
        if not self.id:
            raise UserError('Please save the quiz before using Bulk Add.')

        ids = [int(v) for v in re.findall(r'\d+', self.bulk_add_question_ids_text or '')]
        if not ids:
            raise UserError('Please paste at least one numeric question ID.')

        ordered_unique_ids = list(dict.fromkeys(ids))
        questions = self.env['quiz.question'].search([('id', 'in', ordered_unique_ids)])
        found_map = {q.id: q for q in questions}
        ordered_questions = self.env['quiz.question'].browse([
            qid for qid in ordered_unique_ids if qid in found_map
        ])

        self.bulk_add_question_ids = [(6, 0, ordered_questions.ids)]

        missing_ids = [qid for qid in ordered_unique_ids if qid not in found_map]
        if missing_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Check Completed With Missing IDs',
                    'message': (
                        f'Loaded {len(ordered_questions)} question(s). '
                        f'Missing IDs: {", ".join(str(i) for i in missing_ids)}'
                    ),
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                },
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Check Completed',
                'message': f'Loaded {len(ordered_questions)} question(s) for review.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_bulk_add_questions(self):
        self.ensure_one()
        if not self.id:
            raise UserError('Please save the quiz before adding questions.')

        staged_questions = self.bulk_add_question_ids
        if not staged_questions:
            raise UserError('No staged questions found. Click Check first.')

        existing_ids = set(self.question_ids.ids)
        to_add = staged_questions.filtered(lambda q: q.id not in existing_ids)
        first_time_questions = to_add.filtered(lambda q: not q.quiz_id and not q.all_quiz_ids)

        if to_add:
            self.question_ids = [(4, q.id) for q in to_add]
        if first_time_questions:
            first_time_questions.write({'quiz_id': self.id})

        self.bulk_add_question_ids = [(5, 0, 0)]

        skipped = len(staged_questions) - len(to_add)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Questions Added',
                'message': (
                    f'Added {len(to_add)} question(s) to this quiz. '
                    f'Skipped {skipped} already-linked question(s).'
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def create_submission_copy(self, source_submission_id):
        """
        Create a copy of an existing aps.resource.submission for resubmission.

        Called by the OWL quiz component (quiz_game.js) when allowResubmission
        is enabled and the student clicks "Resubmit this Quiz".  The copy is
        created using ORM copy() so all required fields are preserved.  The
        due date (whichever field name the APEX module uses) is cleared, and
        score/answer/state are reset to give the student a fresh attempt.

        Returns the ID of the newly created submission.
        """
        Submission = self.env['aps.resource.submission']
        original = Submission.browse(int(source_submission_id))
        if not original.exists():
            raise UserError("Original submission not found.")

        defaults = {
            'score': 0,
            'answer': False,
            'state': 'assigned',
        }
        # Clear the due date on the copy so the student gets an open-ended
        # resubmission with no deadline.  The APEX module (aps_sis) may use
        # different field names across versions; clear every date-like field
        # that exists on the model rather than stopping at the first match.
        for date_field in (
            'date_due',
        ):
            if date_field in Submission._fields:
                defaults[date_field] = False

        new_sub = original.copy(defaults)
        return new_sub.id

    @api.model
    def get_quiz_for_student(self, quiz_id, question_count=0, option_count=0, quiz_token=None):
        """
        Return quiz data with randomised answer order for the student view.
        Correct-answer flags are NOT included to prevent client-side cheating;
        validation is performed server-side in submit_quiz_answers.

        :param quiz_id: int – ID of the quiz to load
        :param question_count: int – accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param option_count: int – accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param quiz_token: str – signed token produced by _build_quiz_token().
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        allow_resubmission = False

        # Signed token mode: trust only values encoded in the token.
        if quiz_token:
            token_data = self._decode_quiz_token(quiz_token)
            if not token_data or token_data['quiz_id'] != quiz.id:
                raise UserError("Invalid quiz link.")
            q_limit = token_data['question_count']
            o_limit = token_data['option_count']
            allow_resubmission = token_data['allow_resubmission']
            filter_payload = self._normalize_quiz_filter_payload(token_data)
        else:
            # Unsigned URL parameters are intentionally ignored so students
            # cannot lower difficulty by editing query parameters.
            q_limit = 0
            o_limit = 0
            filter_payload = self._normalize_quiz_filter_payload({})

        rng = random.SystemRandom()

        all_questions = list(quiz.question_ids)

        student_stats = self._get_student_question_attempt_stats(quiz.question_ids, self.env.user)

        all_questions = [
            question for question in all_questions
            if self._question_matches_filter_payload(question, filter_payload, student_stats)
        ]

        if q_limit > 0 and q_limit < len(all_questions):
            all_questions = rng.sample(all_questions, q_limit)

        # Pre-fetch incorrect response counts for every question in this quiz so
        # we can pick the "most-often-wrong" distractor without N+1 queries.
        # result: {question_id: {answer_id: count, ...}, ...}
        wrong_response_counts = {}
        if o_limit > 0:
            question_ids = [q.id for q in all_questions]
            wrong_responses = self.env['quiz.response'].sudo().read_group(
                domain=[
                    ('question_id', 'in', question_ids),
                    ('is_correct', '=', False),
                ],
                fields=['question_id', 'answer_id'],
                groupby=['question_id', 'answer_id'],
                lazy=False,
            )
            for row in wrong_responses:
                qid = row['question_id'][0]
                aid = row['answer_id'][0]
                wrong_response_counts.setdefault(qid, {})[aid] = row['__count']

        questions = []
        for question in all_questions:
            all_answers = list(question.answer_ids)
            question_student_stats = student_stats.get(
                question.id,
                {'attempt_count': 0, 'weighted_score_pct': None},
            )

            if o_limit > 0 and o_limit < len(all_answers):
                correct = [a for a in all_answers if a.is_correct]
                wrong = [a for a in all_answers if not a.is_correct]

                # Pin the most-often-selected incorrect answer as a guaranteed distractor
                counts = wrong_response_counts.get(question.id, {})
                if counts and wrong:
                    top_wrong = max(wrong, key=lambda a: counts.get(a.id, 0))
                    remaining_wrong = [a for a in wrong if a is not top_wrong]
                    pinned_wrong = [top_wrong]
                else:
                    pinned_wrong = []
                    remaining_wrong = wrong

                # Fill remaining slots with random wrong answers
                keep_wrong = max(0, o_limit - len(correct) - len(pinned_wrong))
                selected = correct + pinned_wrong + rng.sample(remaining_wrong, min(keep_wrong, len(remaining_wrong)))
                rng.shuffle(selected)
                answers = selected
            else:
                answers = all_answers
                rng.shuffle(answers)

            questions.append({
                'id': question.id,
                'question_text': question.question_text or '',
                'marks': question.marks,
                'allow_multiple': question.allow_multiple,
                'student_attempt_count': question_student_stats['attempt_count'],
                'student_weighted_score_pct': round(question_student_stats['weighted_score_pct'] or 0),
                'answers': [
                    {
                        'id': a.id,
                        'answer_text': a.answer_text or '',
                    }
                    for a in answers
                ],
            })

        displayed_marks = sum(q['marks'] for q in questions)
        is_teacher = (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        )
        return {
            'id': quiz.id,
            'name': quiz.name,
            'total_marks': displayed_marks,
            'allow_resubmission': allow_resubmission,
            'filter_summary': quiz._build_filter_summary(filter_payload),
            # quiz.id is always a positive integer from the ORM; safe for URL use
            'header_image_url': (
                f'/web/image/quiz.quiz/{quiz.id}/header_image'
                if quiz.header_image
                else '/educational_games/static/src/img/quiz_bg.jpg'
            ),
            'questions': questions,
            'is_teacher': is_teacher,
        }

    @api.model
    def submit_quiz_answers(self, quiz_id, answers, quiz_token=None):
        """
        Validate answers server-side and return scoring details.

        :param quiz_id: int – ID of the quiz being submitted
        :param answers: dict[str, list[int]] – mapping of str(question_id) to
                        list of selected answer IDs
        :returns: dict with keys score, total_marks, results
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        token_data = self._decode_quiz_token(quiz_token) if quiz_token else None
        filter_payload = self._normalize_quiz_filter_payload(token_data or {})
        has_active_filters = any([
            token_data and token_data.get('question_count'),
            token_data and token_data.get('option_count'),
            filter_payload['filter_tag_ids'],
            filter_payload['filter_subject_ids'],
            filter_payload['filter_min_attempts'] is not None,
            filter_payload['filter_max_attempts'] is not None,
            filter_payload['filter_max_pct_correct'] is not None,
            filter_payload['filter_student_weighted_score_pct'] is not None,
            filter_payload['filter_student_attempts'] is not None,
        ])

        score = 0
        results = []
        total_marks = 0
        attempted_question_count = 0

        # Only score the questions that the student actually received (keys in answers)
        submitted_ids = {int(k) for k in answers}
        questions_to_score = quiz.question_ids.filtered(lambda q: q.id in submitted_ids) if submitted_ids else quiz.question_ids

        for question in questions_to_score:
            q_id = str(question.id)
            selected_ids = set(int(i) for i in (answers.get(q_id) or []))
            correct_ids = set(question.answer_ids.filtered('is_correct').ids)

            if selected_ids:
                attempted_question_count += 1

            is_correct = bool(correct_ids) and selected_ids == correct_ids
            if is_correct:
                score += question.marks
            total_marks += question.marks

            answer_details = [
                {
                    'id': a.id,
                    'answer_text': a.answer_text or '',
                    'is_correct': a.is_correct,
                    'was_selected': a.id in selected_ids,
                }
                for a in question.answer_ids
            ]
            results.append({
                'question_id': question.id,
                'question_text': question.question_text or '',
                'is_correct': is_correct,
                'correct_answer_ids': list(correct_ids),
                'selected_answer_ids': list(selected_ids),
                'marks': question.marks,
                'answers': answer_details,
            })

        if not has_active_filters and attempted_question_count < len(questions_to_score):
            total_marks = max(10, attempted_question_count)

        # Persist one quiz.response record for every answer the student selected
        response_vals = []
        attempt_tokens = {result['question_id']: uuid.uuid4().hex for result in results}
        for r in results:
            for a in r['answers']:
                if a['was_selected']:
                    response_vals.append({
                        'quiz_id': quiz.id,
                        'question_id': r['question_id'],
                        'answer_id': a['id'],
                        'user_id': self.env.user.id,
                        'attempt_token': attempt_tokens[r['question_id']],
                        'is_correct': a['is_correct'],
                    })
        if response_vals:
            self.env['quiz.response'].sudo().create(response_vals)

        # Recompute stored stats on affected questions and their answers.
        # Use sudo() because students do not have write access to quiz.question
        # or quiz.answer (the stats fields are teacher-facing read-only counters).
        affected_q_ids = [r['question_id'] for r in results]
        self.env['quiz.question'].sudo()._recompute_stats(affected_q_ids)

        # ── Per-question response stats for teacher users ────────────────
        is_teacher = (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        )
        if is_teacher:
            cutoff = fields.Datetime.now() - timedelta(hours=1)
            all_responses = self.env['quiz.response'].search([('quiz_id', '=', quiz.id)])
            recent_responses = all_responses.filtered(
                lambda r: r.create_date and r.create_date >= cutoff
            )
            # Pre-bucket by question so we only loop responses once
            from collections import defaultdict
            all_by_q = defaultdict(list)
            recent_by_q = defaultdict(list)
            for r in all_responses:
                all_by_q[r.question_id.id].append(r.answer_id.id)
            for r in recent_responses:
                recent_by_q[r.question_id.id].append(r.answer_id.id)

            for res in results:
                qid = res['question_id']
                q_all = all_by_q[qid]
                q_recent = recent_by_q[qid]
                total_n = len(q_all)
                recent_n = len(q_recent)
                show_dual = total_n > 0 and recent_n > 0 and recent_n < total_n
                total_by_ans = Counter(q_all)
                recent_by_ans = Counter(q_recent)
                response_stats = {}
                for a in res['answers']:
                    a_id = a['id']
                    a_total = total_by_ans.get(a_id, 0)
                    a_recent = recent_by_ans.get(a_id, 0)
                    response_stats[str(a_id)] = {
                        'total_count': a_total,
                        'total_pct': round(a_total / total_n * 100) if total_n else 0,
                        'recent_count': a_recent,
                        'recent_pct': round(a_recent / recent_n * 100) if recent_n else 0,
                        'show_recent': show_dual,
                    }
                res['response_stats'] = response_stats
                res['show_dual'] = show_dual
                res['total_respondents'] = total_n
                res['recent_respondents'] = recent_n
        # ─────────────────────────────────────────────────────────────────

        return {
            'score': score,
            'total_marks': total_marks,
            'results': results,
            'is_teacher': is_teacher,
        }

    @api.model
    def check_single_question(self, quiz_id, question_id):
        """
        For teachers: reveal the correct answer(s) for a single question without
        submitting the whole quiz.  Only accessible to users in group_aps_teacher
        or group_aps_manager.

        :param quiz_id:     int – ID of the quiz the question belongs to
        :param question_id: int – ID of the question to reveal
        :returns: dict compatible with the per-question entries in submit_quiz_answers
                  results list, with an additional ``selected_answer_ids`` key set
                  from the caller-supplied selections (passed as ``selected_ids``).
        """
        if not (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        ):
            raise AccessError("Only teachers can check individual answers.")

        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        question = self.env['quiz.question'].browse(int(question_id))
        if not question.exists() or question.quiz_id.id != quiz.id:
            raise UserError("Question not found in this quiz.")

        correct_ids = set(question.answer_ids.filtered('is_correct').ids)

        # ── Response statistics ────────────────────────────────────────────
        cutoff = fields.Datetime.now() - timedelta(hours=1)
        all_responses = self.env['quiz.response'].search(
            [('question_id', '=', question.id)]
        )
        recent_responses = all_responses.filtered(
            lambda r: r.create_date and r.create_date >= cutoff
        )
        total_n = len(all_responses)
        recent_n = len(recent_responses)

        # show_dual: True when there are BOTH older and recent responses so we
        # need to display two separate percentages (total vs. last-60-min).
        # If all responses fall within the last hour there is no need for a
        # second figure — they are identical.
        show_dual = total_n > 0 and recent_n > 0 and recent_n < total_n

        # Count selections per answer in a single pass for O(n) complexity
        total_by_ans = Counter(r.answer_id.id for r in all_responses)
        recent_by_ans = Counter(r.answer_id.id for r in recent_responses)

        response_stats = {}
        for a in question.answer_ids:
            a_total = total_by_ans.get(a.id, 0)
            a_recent = recent_by_ans.get(a.id, 0)
            response_stats[str(a.id)] = {
                'total_count': a_total,
                'total_pct': round(a_total / total_n * 100) if total_n else 0,
                'recent_count': a_recent,
                'recent_pct': round(a_recent / recent_n * 100) if recent_n else 0,
                'show_recent': show_dual,
            }
        # ──────────────────────────────────────────────────────────────────

        return {
            'question_id': question.id,
            'question_text': question.question_text or '',
            'correct_answer_ids': list(correct_ids),
            'marks': question.marks,
            'answers': [
                {
                    'id': a.id,
                    'answer_text': a.answer_text or '',
                    'is_correct': a.is_correct,
                }
                for a in question.answer_ids
            ],
            'response_stats': response_stats,
            'show_dual': show_dual,
            'total_respondents': total_n,
            'recent_respondents': recent_n,
        }

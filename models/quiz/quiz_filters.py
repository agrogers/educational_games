from collections import Counter
from datetime import timedelta

from odoo import api, models


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    @staticmethod
    def _sanitize_nonnegative_int(value):
        if value in (False, None, ''):
            return 0
        return max(0, int(str(value).strip() or 0))

    def _get_quiz_filter_payload(self):
        return {
            'filter_tag_ids': sorted(self.filter_tag_ids.ids),
            'filter_exclude_tag_ids': sorted(self.filter_exclude_tag_ids.ids),
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
            'filter_exclude_tag_ids': sorted(int(tag_id) for tag_id in (payload.get('filter_exclude_tag_ids') or [])),
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
        if filter_payload['filter_exclude_tag_ids']:
            tags = self.env['quiz.tag'].sudo().browse(filter_payload['filter_exclude_tag_ids']).exists().mapped('name')
            parts.append(f"Exclude tags: {', '.join(tags)}")
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
        'filter_exclude_tag_ids',
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
            is_memory_reveal = self[:1].quiz_type == 'memory_reveal'
            maximum_marks = max(question.answer_ids.mapped('marks') or [question.marks or 0])
            weighted_total = 0.0
            weight_sum = 0.0

            for index, attempt in enumerate(attempts, start=1):
                weight = 1.0 / index
                if is_memory_reveal:
                    selected_answer = question.answer_ids.filtered(
                        lambda answer: answer.id in attempt['selected_ids']
                    )[:1]
                    attempt_score = (
                        (selected_answer.marks / maximum_marks) * 100.0
                        if selected_answer and maximum_marks
                        else 0.0
                    )
                else:
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
        if filter_payload['filter_exclude_tag_ids']:
            if set(filter_payload['filter_exclude_tag_ids']).intersection(question.tag_ids.ids):
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

    def _question_matches_static_scope(self, question, filter_payload):
        filter_payload = self._normalize_quiz_filter_payload(filter_payload)

        if filter_payload['filter_tag_ids']:
            if not set(filter_payload['filter_tag_ids']).intersection(question.tag_ids.ids):
                return False
        if filter_payload['filter_exclude_tag_ids']:
            if set(filter_payload['filter_exclude_tag_ids']).intersection(question.tag_ids.ids):
                return False

        if filter_payload['filter_subject_ids']:
            if not set(filter_payload['filter_subject_ids']).intersection(question.subject_ids.ids):
                return False

        return True

    def _build_student_progress_summary(self, quiz, filter_payload, student_stats):
        filter_payload = self._normalize_quiz_filter_payload(filter_payload)
        student_attempt_threshold = filter_payload['filter_student_attempts']
        student_weighted_threshold = filter_payload['filter_student_weighted_score_pct'] or 80

        scoped_questions = quiz.question_ids.filtered(lambda question: self._question_matches_static_scope(question, filter_payload))
        total_possible_questions = len(scoped_questions)

        known_questions = 0           # attempts â‰¥ threshold AND score â‰¥ threshold
        not_known_questions = 0        # attempts â‰¥ threshold AND score < threshold
        new_above_threshold = 0        # 0 < attempts < threshold AND score â‰¥ threshold
        new_below_threshold = 0        # 0 < attempts < threshold AND score < threshold
        not_tried_questions = 0        # attempts == 0

        # When no explicit attempt threshold is configured we still want to
        # distinguish "tried once" (new) from "reviewed multiple times" (known).
        # Use a default minimum of 2 attempts to count as properly reviewed.
        effective_threshold = student_attempt_threshold if student_attempt_threshold else 2

        for question in scoped_questions:
            question_stats = student_stats.get(
                question.id,
                {'attempt_count': 0, 'weighted_score_pct': None, 'last_answered_at': None},
            )
            attempt_count = question_stats['attempt_count'] or 0
            weighted_score = question_stats['weighted_score_pct']

            meets_weighted_threshold = (
                weighted_score is not None and weighted_score >= student_weighted_threshold
            )

            if attempt_count == 0:
                not_tried_questions += 1
            elif attempt_count < effective_threshold:
                # Tried but not yet reviewed enough times
                if meets_weighted_threshold:
                    new_above_threshold += 1
                else:
                    new_below_threshold += 1
            else:
                # Reviewed enough (attempts â‰¥ threshold)
                if meets_weighted_threshold:
                    known_questions += 1
                else:
                    not_known_questions += 1

        questions_with_results_data = known_questions + not_known_questions + new_above_threshold + new_below_threshold

        progress_text = ''
        if total_possible_questions:
            progress_text = (
                f'This quiz has {total_possible_questions} questions.  '
                f'You have scored {student_weighted_threshold}% or more in {known_questions} out of '
                f'the {questions_with_results_data} we have results data for.'
            )
            if student_attempt_threshold:
                progress_text = f'{progress_text} (ie questions you have attempted at least {student_attempt_threshold} times).'

        return {
            'total_possible_questions': total_possible_questions,
            'questions_with_results_data': questions_with_results_data,
            'known_questions': known_questions,
            'not_known_questions': not_known_questions,
            'new_above_threshold': new_above_threshold,
            'new_below_threshold': new_below_threshold,
            'not_tried_questions': not_tried_questions,
            'student_attempt_threshold': student_attempt_threshold,
            'student_weighted_threshold': student_weighted_threshold,
            'progress_text': progress_text,
        }


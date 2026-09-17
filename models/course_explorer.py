import logging
import time

from odoo import models


_logger = logging.getLogger(__name__)


class EducationalGamesCourseExplorer(models.Model):
    """Educational Games contribution to the APS Course Explorer progress."""

    _inherit = 'aps.resources'

    @staticmethod
    def _normalise_tag_name(name):
        return (name or '').strip().casefold()

    def _get_course_explorer_quiz_progress(self, resources, student_id):
        """Calculate the quiz half of Course Explorer progress.

        A resource's chapter is identified by its ``Ch...`` resource tags.
        Questions are scoped by the resource subjects and matching question
        tags.  A question counts as attempted when the current Odoo user has
        at least one response for it, regardless of correctness.

        ``student_id`` is intentionally not used to identify quiz responses:
        Educational Games stores responses against ``res.users`` while APS
        stores students as ``res.partner``.  The current user is the only
        trusted response identity for this student-facing calculation.
        """
        started_at = time.perf_counter()
        question_model = self.env['quiz.question'].sudo()
        response_model = self.env['quiz.response'].sudo()

        resource_tags = {}
        subject_ids = set()
        for resource in resources:
            chapter_names = {
                self._normalise_tag_name(tag.name)
                for tag in resource.tag_ids
                if self._normalise_tag_name(tag.name).startswith('ch')
            }
            resource_tags[resource.id] = chapter_names
            subject_ids.update(resource.subjects.ids)

        if not subject_ids:
            _logger.info(
                "Course Explorer quiz lookup: no subjects for %d resources; "
                "finished in %.3fs",
                len(resources),
                time.perf_counter() - started_at,
            )
            return {
                resource.id: self._empty_quiz_progress()
                for resource in resources
            }

        candidate_questions = question_model.search([
            ('subject_ids', 'in', list(subject_ids)),
        ])
        _logger.info(
            "Course Explorer quiz lookup: scanned %d resources, %d subjects, "
            "found %d candidate questions in %.3fs",
            len(resources),
            len(subject_ids),
            len(candidate_questions),
            time.perf_counter() - started_at,
        )

        progress = {}
        resource_question_ids = {}
        question_ids_by_tag = {}
        question_subject_ids = {}
        for question in candidate_questions:
            question_subject_ids[question.id] = set(question.subject_ids.ids)
            for tag in question.tag_ids:
                tag_name = self._normalise_tag_name(tag.name)
                question_ids_by_tag.setdefault(tag_name, set()).add(question.id)

        matching_started_at = time.perf_counter()
        for resource in resources:
            if resource.has_notes == 'no':
                progress[resource.id] = {
                    'quizProgress': 0.0,
                    'quizQuestionCount': 0,
                    'quizAnsweredQuestionCount': 0,
                    'quizCompletionPercent': 0.0,
                }
                continue
            chapter_names = resource_tags[resource.id]
            resource_subject_ids = set(resource.subjects.ids)
            question_ids = set().union(
                *(question_ids_by_tag.get(tag_name, set()) for tag_name in chapter_names)
            ) if chapter_names else set()
            question_ids = {
                question_id for question_id in question_ids
                if question_subject_ids[question_id].intersection(resource_subject_ids)
            }
            resource_question_ids[resource.id] = question_ids
            if not question_ids:
                progress[resource.id] = self._empty_quiz_progress()
                continue

        _logger.info(
            "Course Explorer quiz lookup: matched questions to resources in "
            "%.3fs",
            time.perf_counter() - matching_started_at,
        )

        all_question_ids = set().union(*resource_question_ids.values()) if resource_question_ids else set()
        response_started_at = time.perf_counter()
        answered_question_ids = set()
        if all_question_ids:
            answered_groups = response_model.read_group(
                [
                    ('question_id', 'in', list(all_question_ids)),
                    ('user_id', '=', self.env.user.id),
                ],
                ['question_id'],
                ['question_id'],
            )
            answered_question_ids = {
                group['question_id'][0]
                for group in answered_groups
                if group.get('question_id')
            }
        _logger.info(
            "Course Explorer quiz lookup: response aggregate took %.3fs "
            "(%d answered questions)",
            time.perf_counter() - response_started_at,
            len(answered_question_ids),
        )

        for resource in resources:
            question_ids = resource_question_ids.get(resource.id, set())
            if not question_ids:
                continue
            answered_ids = question_ids & answered_question_ids
            answered_count = len(answered_ids)
            total_count = len(question_ids)
            completion = round(answered_count / total_count * 100.0, 1)
            progress[resource.id] = {
                'quizProgress': round(completion * 0.5, 1),
                'quizQuestionCount': total_count,
                'quizAnsweredQuestionCount': answered_count,
                'quizCompletionPercent': completion,
            }

        _logger.info(
            "Course Explorer quiz lookup: checked %d distinct questions with "
            "one batched response lookup; total %.3fs",
            len(all_question_ids),
            time.perf_counter() - started_at,
        )

        return progress

    @staticmethod
    def _empty_quiz_progress():
        return {
            'quizProgress': 0.0,
            'quizQuestionCount': 0,
            'quizAnsweredQuestionCount': 0,
            'quizCompletionPercent': 0.0,
        }
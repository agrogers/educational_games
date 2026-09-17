from odoo import models


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
            return {
                resource.id: self._empty_quiz_progress()
                for resource in resources
            }

        candidate_questions = question_model.search([
            ('subject_ids', 'in', list(subject_ids)),
        ])

        progress = {}
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
            questions = candidate_questions.filtered(
                lambda question: bool(
                    chapter_names.intersection(
                        self._normalise_tag_name(tag.name)
                        for tag in question.tag_ids
                    )
                ) and bool(set(question.subject_ids.ids).intersection(resource.subjects.ids))
            )
            question_ids = set(questions.ids)
            if not question_ids:
                progress[resource.id] = self._empty_quiz_progress()
                continue

            answered_ids = set(response_model.search([
                ('question_id', 'in', list(question_ids)),
                ('user_id', '=', self.env.user.id),
            ]).mapped('question_id').ids)
            answered_count = len(answered_ids)
            total_count = len(question_ids)
            completion = round(answered_count / total_count * 100.0, 1)
            progress[resource.id] = {
                'quizProgress': round(completion * 0.5, 1),
                'quizQuestionCount': total_count,
                'quizAnsweredQuestionCount': answered_count,
                'quizCompletionPercent': completion,
            }

        return progress

    @staticmethod
    def _empty_quiz_progress():
        return {
            'quizProgress': 0.0,
            'quizQuestionCount': 0,
            'quizAnsweredQuestionCount': 0,
            'quizCompletionPercent': 0.0,
        }
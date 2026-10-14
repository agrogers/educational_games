import re

from odoo import api, models
from odoo.exceptions import UserError


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    @api.depends(
        'display_question_count',
        'display_option_count',
        'allow_resubmission',
        'filter_tag_ids',
        'filter_exclude_tag_ids',
        'quiz_type',
        'filter_subject_ids',
        'filter_min_attempts',
        'filter_max_attempts',
        'filter_max_pct_correct',
        'filter_student_weighted_score_pct',
        'filter_student_attempts',
        'filter_exclude_answered_days',
    )
    def _compute_quiz_url_params(self):
        # Resolve both client action IDs once for the batch.  The format APEX
        # expects is: action:<action_id>?quiz_id=<id>&quiz_token=<signed>
        try:
            standard_action_id = self.env.ref('educational_games.action_quiz_game').id
            memory_action_id = self.env.ref('educational_games.action_memory_reveal_game').id
        except ValueError:
            # External ID not found â€” log a warning so it is easy to diagnose
            import logging
            logging.getLogger(__name__).warning(
                "Educational Games client action not found; quiz URL will not contain a valid action ID."
            )
            standard_action_id = memory_action_id = 'UNKNOWN'

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
            action_id = (
                memory_action_id
                if record.quiz_type == 'memory_reveal'
                else standard_action_id
            )
            record.quiz_url_params = f'action:{action_id}?{"&".join(parts)}'

    def action_preview_quiz(self):
        """Launch the student quiz view in preview/practice mode.

        For memory_reveal quizzes, opens the Memory Reveal game instead.
        """
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before previewing.")

        # Memory Reveal quizzes use a dedicated game view
        if self.quiz_type == 'memory_reveal':
            return {
                'type': 'ir.actions.client',
                'tag': 'action_memory_reveal_game_js',
                'name': self.name,
                'params': {'quiz_id': quiz_id},
                'context': {'quiz_id': quiz_id},
            }

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

    def action_open_filtered_question_list(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Question List',
            'res_model': 'quiz.question',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.filtered_question_ids.ids)],
            'context': {
                'search_default_all_quiz_ids': self.id,
            },
            'target': 'current',
        }

    def action_open_create_resource_wizard(self):
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before creating a resource.")
        if not self.quiz_url_params:
            raise UserError("The quiz URL is not available. Please save the quiz and try again.")

        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Resource',
            'res_model': 'quiz.resource.create.wizard',
            'view_mode': 'form',
            'views': [(
                self.env.ref(
                    'educational_games.view_quiz_resource_create_wizard_form'
                ).id,
                'form',
            )],
            'target': 'new',
            'context': {
                'default_quiz_id': quiz_id,
            },
        }

    def action_delete_all_questions(self):
        """Delete all questions (and their cascaded answers) for this quiz.

        Questions whose primary quiz (quiz_id) is this quiz are permanently
        deleted.  Questions shared from another primary quiz are only removed
        from this quiz's question_ids relation â€” they remain intact.
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

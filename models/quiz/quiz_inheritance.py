from odoo import api, models
from odoo.exceptions import ValidationError


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    def _sync_inherited_questions(self):
        """Sync question_ids to include questions from include_other_quizzes.

        inherited_question_ids tracks which questions were auto-added so we
        know which ones to remove safely when an included quiz is removed.
        Only questions that are no longer inherited AND were not also manually
        added are removed from question_ids.
        """
        for quiz in self.exists():
            visited_quiz_ids = set()
            new_inherited_ids = set()

            def _collect(q):
                if q.id in visited_quiz_ids:
                    return
                visited_quiz_ids.add(q.id)
                # Apply each included quiz's static filters before its
                # questions are inherited.  Runtime/student filters are
                # still applied by the quiz that is ultimately played.
                new_inherited_ids.update(q._filtered_questions().ids)
                for included in q.include_other_quizzes:
                    _collect(included)

            for included in quiz.include_other_quizzes:
                _collect(included)

            current_question_ids = set(quiz.question_ids.ids)
            old_inherited_ids = set(quiz.inherited_question_ids.ids)
            manual_question_ids = set(quiz.manual_question_ids.ids)

            # Records created before manual_question_ids was introduced may
            # not have any provenance data yet. Preserve their current
            # non-inherited links as manual links the first time they sync.
            if not manual_question_ids:
                manual_question_ids = current_question_ids - old_inherited_ids
                if manual_question_ids:
                    quiz.with_context(
                        skip_quiz_manual_tracking=True,
                    ).write({
                        'manual_question_ids': [(6, 0, list(manual_question_ids))],
                    })

            to_add = new_inherited_ids - current_question_ids
            to_remove = old_inherited_ids - new_inherited_ids - manual_question_ids

            # Update the hidden tracking set
            quiz.with_context(
                skip_quiz_manual_tracking=True,
            ).write({
                'inherited_question_ids': [
                    (6, 0, list(new_inherited_ids)),
                ],
            })
            # Propagate changes into question_ids
            if to_add:
                quiz.with_context(
                    skip_quiz_manual_tracking=True,
                ).write({
                    'question_ids': [(4, qid) for qid in to_add],
                })
            if to_remove:
                quiz.with_context(
                    skip_quiz_manual_tracking=True,
                ).write({
                    'question_ids': [(3, qid) for qid in to_remove],
                })

    @api.constrains('include_other_quizzes')
    def _check_no_circular_include(self):
        """Raise a ValidationError if including another quiz would create a
        circular dependency (A includes B includes ... includes A)."""
        for record in self:
            visited = set()

            def _is_reachable(quiz):
                if quiz.id in visited:
                    return False
                if quiz.id == record.id:
                    return True
                visited.add(quiz.id)
                return any(_is_reachable(inc) for inc in quiz.include_other_quizzes)

            for included in record.include_other_quizzes:
                visited.clear()
                if _is_reachable(included):
                    raise ValidationError(
                        f"Circular reference detected: including '{included.name}' "
                        f"would create a cycle."
                    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        # Capture questions supplied on the initial create as manual links
        # before materialized inherited questions are added.
        for record in records:
            if record.question_ids:
                record.with_context(
                    skip_quiz_manual_tracking=True,
                ).write({
                    'manual_question_ids': [(6, 0, record.question_ids.ids)],
                })

        records._sync_inherited_questions()
        return records

    def write(self, vals):
        old_question_ids = {
            record.id: set(record.question_ids.ids)
            for record in self
        }
        old_inherited_ids = {
            record.id: set(record.inherited_question_ids.ids)
            for record in self
        }
        old_manual_ids = {
            record.id: set(record.manual_question_ids.ids)
            for record in self
        }

        result = super().write(vals)

        if 'question_ids' in vals and not self.env.context.get(
            'skip_quiz_manual_tracking'
        ):
            for record in self:
                current_ids = set(record.question_ids.ids)
                retained_manual_ids = old_manual_ids[record.id] & current_ids
                newly_added_ids = (
                    current_ids
                    - old_question_ids[record.id]
                    - old_inherited_ids[record.id]
                )
                manual_ids = retained_manual_ids | newly_added_ids
                record.with_context(
                    skip_quiz_manual_tracking=True,
                ).write({
                    'manual_question_ids': [(6, 0, list(manual_ids))],
                })

        if 'include_other_quizzes' in vals:
            self._sync_inherited_questions()
        if 'question_ids' in vals:
            # Re-sync any quizzes that include self so their inherited set stays current.
            including_quizzes = self.env['quiz.quiz'].search(
                [('include_other_quizzes', 'in', self.ids)]
            )
            if including_quizzes:
                including_quizzes._sync_inherited_questions()
        if {'filter_tag_ids', 'filter_exclude_tag_ids', 'filter_subject_ids'}.intersection(vals) and not self.env.context.get('skip_quiz_filter_sync'):
            # A source quiz's static filters determine which questions it
            # contributes, including through transitive inheritance.
            including_quizzes = self.env['quiz.quiz'].search(
                [('include_other_quizzes', 'in', self.ids)]
            )
            if including_quizzes:
                including_quizzes._sync_inherited_questions()
        return result

    def unlink(self):
        including_quizzes = self.env['quiz.quiz'].search([
            ('include_other_quizzes', 'in', self.ids),
        ])
        result = super().unlink()
        including_quizzes = including_quizzes.exists()
        if including_quizzes:
            including_quizzes._sync_inherited_questions()
        return result

    @api.model
    def _cron_sync_inherited_questions(self):
        """Repair materialized inherited question links once per day."""
        quizzes = self.sudo().search([])
        quizzes._sync_inherited_questions()
        return True




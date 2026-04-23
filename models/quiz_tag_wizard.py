from odoo import models, fields
from odoo.exceptions import UserError


class QuizQuestionTagWizard(models.TransientModel):
    _name = 'quiz.question.tag.wizard'
    _description = 'Bulk Modify Questions'

    question_ids = fields.Many2many(
        'quiz.question',
        string='Questions to Update',
        default=lambda self: [(6, 0, self.env.context.get('active_ids', []))],
        readonly=True,
    )
    update_tags = fields.Boolean(string='Update Tags', default=False)
    tags_add_ids = fields.Many2many(
        'quiz.tag',
        'wizard_quiz_tag_add_rel',
        'wizard_id',
        'tag_id',
        string='Tags to Add',
    )
    tags_remove_ids = fields.Many2many(
        'quiz.tag',
        'wizard_quiz_tag_remove_rel',
        'wizard_id',
        'tag_id',
        string='Tags to Remove',
    )
    update_subjects = fields.Boolean(string='Update Subjects', default=False)
    subjects_add_ids = fields.Many2many(
        'aps.subject',
        'wizard_quiz_subject_add_rel',
        'wizard_id',
        'subject_id',
        string='Subjects to Add',
    )
    subjects_remove_ids = fields.Many2many(
        'aps.subject',
        'wizard_quiz_subject_remove_rel',
        'wizard_id',
        'subject_id',
        string='Subjects to Remove',
    )

    def apply_changes(self):
        """Apply bulk tag and subject changes to the selected questions."""
        self.ensure_one()
        questions = self.question_ids
        if not questions:
            raise UserError('No questions were selected for bulk modification.')

        if not self.update_tags and not self.update_subjects:
            raise UserError('Please enable at least one update option.')

        if self.update_tags:
            if not self.tags_add_ids and not self.tags_remove_ids:
                raise UserError('Please choose at least one tag to add or remove.')
            tag_commands = [(4, tag.id) for tag in self.tags_add_ids]
            tag_commands += [(3, tag.id) for tag in self.tags_remove_ids]
            if tag_commands:
                questions.write({'tag_ids': tag_commands})

        if self.update_subjects:
            if not self.subjects_add_ids and not self.subjects_remove_ids:
                raise UserError('Please choose at least one subject to add or remove.')
            subject_commands = [(4, subject.id) for subject in self.subjects_add_ids]
            subject_commands += [(3, subject.id) for subject in self.subjects_remove_ids]
            if subject_commands:
                questions.write({'subject_ids': subject_commands})

        return {'type': 'ir.actions.act_window_close'}

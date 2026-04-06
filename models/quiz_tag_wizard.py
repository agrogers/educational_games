from odoo import models, fields, api


class QuizQuestionTagWizard(models.TransientModel):
    _name = 'quiz.question.tag.wizard'
    _description = 'Bulk Assign Tags to Questions'

    tag_ids = fields.Many2many(
        'quiz.tag',
        'wizard_quiz_tag_rel',
        'wizard_id',
        'tag_id',
        string='Tags to Assign',
        required=True,
    )

    def apply_tags(self):
        """Assign selected tags to all selected questions."""
        active_ids = self.env.context.get('active_ids', [])
        questions = self.env['quiz.question'].browse(active_ids)
        
        for question in questions:
            question.tag_ids = [(4, tag.id) for tag in self.tag_ids]
        
        return {'type': 'ir.actions.act_window_close'}

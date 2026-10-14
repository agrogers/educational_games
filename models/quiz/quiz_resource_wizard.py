from odoo import fields, models, _
from odoo.exceptions import UserError


class QuizResourceWizard(models.TransientModel):
    _name = 'quiz.resource.create.wizard'
    _description = 'Create Quiz Resource'

    quiz_id = fields.Many2one(
        'quiz.quiz',
        string='Quiz',
        required=True,
        readonly=True,
    )
    parent_resource_id = fields.Many2one(
        'aps.resources',
        string='Supporting Parent',
        required=True,
    )

    def action_create_resource(self):
        self.ensure_one()
        quiz = self.quiz_id
        if not quiz or not quiz.id:
            raise UserError(_("Please save the quiz before creating a resource."))

        quiz_url = quiz.quiz_url_params
        if not quiz_url:
            raise UserError(_("The quiz URL is not available. Please save the quiz and try again."))

        resource_type = self.env['aps.resource.types'].search(
            [('name', '=', 'Quiz')],
            limit=1,
        )
        if not resource_type:
            raise UserError(_("No resource type named 'Quiz' exists. Create that resource type and try again."))

        self.env['aps.resources'].create({
            'name': 'Quiz',
            'type_id': resource_type.id,
            'supporting_parent_ids': [(4, self.parent_resource_id.id)],
            'url': quiz_url,
            'marks': quiz.display_question_count,
            'has_question': 'yes',
            'question': (
                '<p>This is a quiz task. Your score will be updated here automatically.</p>'
            ),
        })
        if self.parent_resource_id.has_supporting_resources != 'yes':
            self.parent_resource_id.write({
                'has_supporting_resources': 'yes',
            })

        return {
            'type': 'ir.actions.act_window_close',
        }

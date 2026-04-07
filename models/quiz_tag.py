from odoo import models, fields


class QuizTag(models.Model):
    _name = 'quiz.tag'
    _description = 'Quiz Question Tag'
    _order = 'name'

    name = fields.Char(string='Tag Name', required=True)
    description = fields.Char(string='Description')

    _sql_constraints = [
        ('name_uniq', 'UNIQUE(name)', 'Tag name must be unique.'),
    ]

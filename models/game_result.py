from odoo import models, fields, api


class GameResult(models.Model):
    _name = 'game.result'
    _description = 'Student Game Scores'

    student_id = fields.Many2one('res.users', string="Student", default=lambda self: self.env.user)
    score = fields.Integer("Final Score")
    game_data = fields.Json("Raw Game Logs") # Store JSON for detailed analysis
    processed = fields.Boolean("Synced to LMS", default=False)

    @api.model
    def save_score(self, score, logs=None):
        # Business logic: Create record and perhaps trigger LMS update
        return self.create({
            'score': score,
            'game_data': logs,
            'student_id': self.env.uid,
        }).id
    


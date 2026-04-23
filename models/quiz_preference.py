from odoo import api, fields, models


class QuizPreference(models.Model):
    _name = "quiz.preference"
    _description = "Per-user quiz display preferences"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
        default=lambda self: self.env.user,
    )
    use_cards = fields.Boolean(default=True)
    font_size_em = fields.Float(default=1.0)
    answer_columns = fields.Integer(default=1)

    _sql_constraints = [
        ("user_uniq", "unique(user_id)", "Only one preference record per user."),
    ]

    @api.model
    def get_preferences(self):
        """Return the current user's quiz display preferences."""
        pref = self.search([("user_id", "=", self.env.uid)], limit=1)
        if pref:
            return {
                "use_cards": pref.use_cards,
                "font_size_em": pref.font_size_em,
                "answer_columns": min(max(int(pref.answer_columns or 1), 1), 4),
            }
        return {
            "use_cards": True,
            "font_size_em": 1.0,
            "answer_columns": 1,
        }

    @api.model
    def set_preferences(self, use_cards, font_size_em, answer_columns=1):
        """Create or update the current user's quiz display preferences."""
        pref = self.search([("user_id", "=", self.env.uid)], limit=1)
        vals = {
            "use_cards": bool(use_cards),
            "font_size_em": float(font_size_em),
            "answer_columns": min(max(int(answer_columns or 1), 1), 4),
        }
        if pref:
            pref.write(vals)
        else:
            vals["user_id"] = self.env.uid
            self.create(vals)
        return True

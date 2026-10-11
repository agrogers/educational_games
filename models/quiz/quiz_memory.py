from odoo import api, models
from odoo.exceptions import AccessError, UserError


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    @api.model
    def submit_memory_reveal_result(
        self, submission_id, score, answer, out_of_marks=None
    ):
        """Save a Memory Reveal result for the owning student.

        Student submission record rules can reject a normal ORM ``write`` when
        the submission's computed visibility has changed while the game is
        open. This method performs the ownership/state checks in the normal
        environment, then writes only the permitted result fields with sudo.
        It avoids granting students general write access to submissions.
        """
        submission = self.env['aps.resource.submission'].sudo().browse(
            int(submission_id)
        ).exists()
        if not submission:
            raise UserError("Submission not found.")
        if submission.student_id != self.env.user.partner_id:
            raise AccessError("You can only submit results for your own submission.")
        if submission.state != 'assigned':
            raise UserError("This submission has already been submitted.")

        values = {
            'score': float(score or 0),
            'answer': answer or '',
            'state': 'submitted',
        }
        if out_of_marks is not None:
            values['out_of_marks'] = float(out_of_marks)
        submission.write(values)
        return {'saved': True, 'submission_id': submission.id}


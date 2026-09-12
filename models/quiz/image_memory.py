from odoo import models, fields, api
from odoo.exceptions import UserError
import uuid


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    image_content = fields.Html(
        string='Image Content',
        help='Rich text content with an image for Memory Reveal quizzes. '
             'The first image found in this HTML will be used as the quiz image. '
             'Students will try to recall what is hidden behind blurred regions.',
    )
    image_url = fields.Char(
        string='Image URL',
        compute='_compute_image_url',
        help='URL to load the quiz image in the frontend.',
    )

    @api.depends('image_content')
    def _compute_image_url(self):
        for record in self:
            # The editor URL can point to an attachment owned by another
            # record when an image is pasted from another HTML field. Serve
            # it through the quiz-authorized controller instead.
            record.image_url = (
                f'/educational_games/memory_reveal/image/{record.id}'
                if record.id and record.image_content
                else False
            )

    @api.model
    def get_memory_reveal_image_url(self, quiz_id):
        """Return an image URL that is stable for all allowed quiz users."""
        quiz = self.browse(int(quiz_id))
        if not quiz.exists() or quiz.quiz_type != 'memory_reveal' or not quiz.image_content:
            return False
        quiz.check_access_rights('read')
        quiz.check_access_rule('read')
        return f'/educational_games/memory_reveal/image/{quiz.id}'

    def action_open_memory_reveal_setup(self):
        """Launch the Memory Reveal teacher setup for this quiz."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before opening the setup.")
        if self.quiz_type != 'memory_reveal':
            raise UserError("This quiz is not a Memory Reveal quiz.")

        return {
            'type': 'ir.actions.client',
            'tag': 'action_memory_reveal_setup_js',
            'name': f"Memory Reveal Setup - {self.name}",
            'params': {'quiz_id': quiz_id},
            'context': {'default_quiz_id': quiz_id},
        }

    def action_preview_memory_reveal(self):
        """Launch the student Memory Reveal game for this quiz."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before previewing.")
        if self.quiz_type != 'memory_reveal':
            raise UserError("This quiz is not a Memory Reveal quiz.")

        quiz_params = {
            'quiz_id': quiz_id,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'action_memory_reveal_game_js',
            'name': self.name,
            'params': quiz_params,
            'context': quiz_params,
        }

    @api.model
    def submit_memory_reveal_assessment(self, quiz_id, question_id, answer_id, attempt_token=None):
        """
        Save a single Memory Reveal self-assessment response.

        Called by the student game each time they self-assess a revealed region.

        :param quiz_id: int
        :param question_id: int – the region (quiz.question)
        :param answer_id: int – the self-assessment answer selected
        :param attempt_token: str – groups responses from the same play session
        :returns: dict with marks_earned, total_score, total_possible
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")
        if quiz.quiz_type != 'memory_reveal':
            raise UserError("This method is only for Memory Reveal quizzes.")

        question = self.env['quiz.question'].browse(int(question_id))
        answer = self.env['quiz.answer'].browse(int(answer_id))
        if not question.exists() or not answer.exists():
            raise UserError("Invalid question or answer.")
        if answer.question_id != question:
            raise UserError("Answer does not belong to this question.")

        token = attempt_token or uuid.uuid4().hex

        # Upsert: if the student already assessed this region in this attempt, update it
        existing = self.env['quiz.response'].sudo().search([
            ('quiz_id', '=', quiz.id),
            ('question_id', '=', question.id),
            ('user_id', '=', self.env.user.id),
            ('attempt_token', '=', token),
        ], limit=1)

        if existing:
            existing.write({
                'answer_id': answer.id,
                'is_correct': answer.is_correct,
            })
        else:
            self.env['quiz.response'].sudo().create({
                'quiz_id': quiz.id,
                'question_id': question.id,
                'answer_id': answer.id,
                'user_id': self.env.user.id,
                'attempt_token': token,
                'is_correct': answer.is_correct,
            })

        # Compute running score for this attempt
        responses = self.env['quiz.response'].sudo().search([
            ('quiz_id', '=', quiz.id),
            ('user_id', '=', self.env.user.id),
            ('attempt_token', '=', token),
        ])
        total_score = sum(r.answer_id.marks for r in responses)
        attempted_questions = responses.mapped('question_id')
        total_possible = sum(
            max(question.answer_ids.mapped('marks') or [question.marks or 0])
            for question in attempted_questions
        )

        return {
            'marks_earned': answer.marks,
            'total_score': total_score,
            'total_possible': total_possible,
            'attempt_token': token,
        }

    @api.model
    def get_memory_reveal_data(self, quiz_id):
        """Return all Memory Reveal regions and the student's flash-card progress."""
        quiz = self.browse(int(quiz_id)).exists()
        if not quiz or quiz.quiz_type != 'memory_reveal':
            raise UserError("This quiz is not a Memory Reveal quiz.")
        quiz.check_access_rights('read')
        quiz.check_access_rule('read')

        questions = quiz.question_ids.sorted(lambda question: (question.sequence, question.id))
        student_stats = quiz._get_student_question_attempt_stats(questions, self.env.user)
        attempt_threshold = quiz._sanitize_nonnegative_int(quiz.filter_student_attempts)
        weighted_threshold = quiz._sanitize_nonnegative_int(
            quiz.filter_student_weighted_score_pct
        )
        full_total = sum(
            max(question.answer_ids.mapped('marks') or [question.marks or 0])
            for question in questions
        )

        category_counts = {
            'known_questions': 0,
            'not_known_questions': 0,
            'new_above_threshold': 0,
            'new_below_threshold': 0,
            'not_tried_questions': 0,
        }
        region_data = []
        for index, question in enumerate(questions):
            stats = student_stats.get(question.id, {})
            attempts = stats.get('attempt_count', 0) or 0
            weighted_score = stats.get('weighted_score_pct')
            has_score_threshold = bool(weighted_threshold)
            has_attempt_threshold = bool(attempt_threshold)
            meets_score = (
                weighted_score is not None and weighted_score >= weighted_threshold
                if has_score_threshold else True
            )
            meets_attempts = attempts >= attempt_threshold if has_attempt_threshold else True
            known = attempts > 0 and meets_score and meets_attempts
            low_score = attempts > 0 and weighted_score is not None and weighted_score < 50

            if attempts == 0:
                category = 'not_tried'
            elif known:
                category = 'known'
            elif low_score:
                category = 'not_known'
            elif has_attempt_threshold and attempts < attempt_threshold:
                category = 'new_above_threshold' if meets_score else 'new_below_threshold'
            else:
                category = 'middle'
            category_key = (
                'not_known_questions' if category == 'not_known'
                else f'{category}_questions'
            )
            if category_key in category_counts:
                category_counts[category_key] += 1

            answers = question.answer_ids.sorted(lambda answer: (answer.sequence, answer.id))
            region_data.append({
                'id': question.id,
                'name': question.question_text or '',
                'x1': question.region_x1,
                'y1': question.region_y1,
                'x2': question.region_x2,
                'y2': question.region_y2,
                'marks': question.marks,
                'answers': [
                    {
                        'id': answer.id,
                        'answer_text': answer.answer_text or '',
                        'marks': answer.marks,
                    }
                    for answer in answers
                ],
                'index': index,
                'attempt_count': attempts,
                'weighted_score_pct': round(weighted_score or 0, 1),
                'last_answered_at': fields.Datetime.to_string(stats['last_answered_at'])
                if stats.get('last_answered_at') else False,
                'category': category,
            })

        return {
            'quiz_name': quiz.name,
            'full_total_marks': full_total,
            'filter_student_attempts': attempt_threshold,
            'filter_student_weighted_score_pct': weighted_threshold,
            'regions': region_data,
            'progress_summary': {
                **category_counts,
                'total_possible_questions': len(questions),
                'progress_text': (
                    f'This quiz has {len(questions)} regions. '
                    f'{category_counts["known_questions"]} are currently known.'
                ),
            },
        }
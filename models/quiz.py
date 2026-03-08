from odoo import models, fields, api
from odoo.exceptions import UserError
from markupsafe import escape, Markup
import random
import re


class Quiz(models.Model):
    _name = 'quiz.quiz'
    _description = 'Quiz'
    _order = 'name'

    name = fields.Char(string='Quiz Name', required=True)
    description = fields.Html(string='Description')
    question_ids = fields.One2many('quiz.question', 'quiz_id', string='Questions')
    question_count = fields.Integer(
        string='Number of Questions',
        compute='_compute_question_count',
        store=True,
    )
    total_marks = fields.Integer(
        string='Total Marks',
        compute='_compute_total_marks',
        store=True,
    )
    bulk_text = fields.Html(
        string='Paste Quiz Text',
        sanitize=True,
        help=(
            'Paste formatted quiz text here to auto-create questions and answers. '
            'Bold the entire question line and each correct answer line. '
            'Example:\n'
            '**1. What is the capital of France?**\n'
            'A) London\n'
            '**B) Paris**\n'
            'C) Berlin'
        ),
    )

    @api.depends('question_ids')
    def _compute_question_count(self):
        for record in self:
            record.question_count = len(record.question_ids)

    @api.depends('question_ids.marks')
    def _compute_total_marks(self):
        for record in self:
            record.total_marks = sum(q.marks for q in record.question_ids)

    def action_parse_bulk_text(self):
        """Parse the bulk_text HTML field and auto-create questions and answers."""
        for record in self:
            if not record.bulk_text or not record.bulk_text.strip():
                raise UserError(
                    "No text to parse. Please paste quiz text into the 'Paste Quiz Text' field first."
                )
            self._parse_and_create_questions(record)
            record.bulk_text = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Successful',
                'message': 'Questions and answers have been created from the pasted text.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _parse_and_create_questions(self, quiz_record):
        """Parse formatted quiz text (HTML or plain) into questions and answers."""
        text = quiz_record.bulk_text or ''
        lines_with_bold = self._extract_lines_from_html(text)

        current_question = None
        existing_sequences = [q.sequence for q in quiz_record.question_ids]
        q_seq = (max(existing_sequences) + 10) if existing_sequences else 10
        ans_seq = 10

        for (line_text, is_bold) in lines_with_bold:
            line_text = line_text.strip()
            if not line_text:
                continue

            # Question: starts with a number followed by . or )
            q_match = re.match(r'^(\d+)[\.\)]\s+(.+)$', line_text)
            if q_match:
                current_question = self.env['quiz.question'].create({
                    'quiz_id': quiz_record.id,
                    'sequence': q_seq,
                    'question_text': Markup('<p>%s</p>') % escape(q_match.group(2)),
                    'marks': 1,
                })
                q_seq += 10
                ans_seq = 10
                continue

            # Answer: starts with a letter followed by ) or .
            a_match = re.match(r'^([A-Za-z])[\)\.]\s+(.+)$', line_text)
            if a_match and current_question:
                self.env['quiz.answer'].create({
                    'question_id': current_question.id,
                    'sequence': ans_seq,
                    'answer_text': Markup('<p>%s</p>') % escape(a_match.group(2)),
                    'is_correct': is_bold,
                })
                ans_seq += 10

    @staticmethod
    def _extract_lines_from_html(html_text):
        """
        Return a list of (text, is_bold) tuples from HTML quiz content.
        A line is considered bold if its primary content is wrapped in <strong>/<b>
        or if the raw text begins with '**'.
        """
        lines = []
        try:
            from lxml import html as lxml_html
            # Use fragment_fromstring to avoid string-interpolating untrusted HTML
            tree = lxml_html.fragment_fromstring(html_text, create_parent='div')
            for elem in tree.iter():
                if elem.tag not in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    continue
                full_text = ''.join(elem.itertext()).strip()
                if not full_text:
                    continue

                is_bold = False
                if full_text.startswith('**'):
                    is_bold = True
                    full_text = full_text.strip('*').strip()
                else:
                    children = list(elem)
                    if children and children[0].tag in ('strong', 'b'):
                        bold_text = ''.join(children[0].itertext()).strip()
                        if bold_text and len(bold_text) >= len(full_text) * 0.5:
                            is_bold = True

                if full_text:
                    lines.append((full_text, is_bold))
        except Exception:
            # Fallback: strip all HTML tags and handle ** markdown
            clean = re.sub(r'<[^>]+>', '\n', html_text)
            for line in clean.split('\n'):
                line = line.strip()
                if not line:
                    continue
                is_bold = line.startswith('**')
                clean_line = line.strip('*').strip()
                if clean_line:
                    lines.append((clean_line, is_bold))
        return lines

    @api.model
    def get_quiz_for_student(self, quiz_id):
        """
        Return quiz data with randomised answer order for the student view.
        Correct-answer flags are NOT included to prevent client-side cheating;
        validation is performed server-side in submit_quiz_answers.
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        questions = []
        for question in quiz.question_ids:
            answers = list(question.answer_ids)
            random.shuffle(answers)
            questions.append({
                'id': question.id,
                'question_text': question.question_text or '',
                'marks': question.marks,
                'answers': [
                    {
                        'id': a.id,
                        'answer_text': a.answer_text or '',
                    }
                    for a in answers
                ],
            })

        return {
            'id': quiz.id,
            'name': quiz.name,
            'total_marks': quiz.total_marks,
            'questions': questions,
        }

    @api.model
    def submit_quiz_answers(self, quiz_id, answers):
        """
        Validate answers server-side and return scoring details.

        :param quiz_id: int – ID of the quiz being submitted
        :param answers: dict[str, list[int]] – mapping of str(question_id) to
                        list of selected answer IDs
        :returns: dict with keys score, total_marks, results
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        score = 0
        results = []

        for question in quiz.question_ids:
            q_id = str(question.id)
            selected_ids = set(int(i) for i in (answers.get(q_id) or []))
            correct_ids = set(question.answer_ids.filtered('is_correct').ids)

            is_correct = bool(correct_ids) and selected_ids == correct_ids
            if is_correct:
                score += question.marks

            results.append({
                'question_id': question.id,
                'question_text': question.question_text or '',
                'is_correct': is_correct,
                'correct_answer_ids': list(correct_ids),
                'selected_answer_ids': list(selected_ids),
                'marks': question.marks,
                'answers': [
                    {
                        'id': a.id,
                        'answer_text': a.answer_text or '',
                        'is_correct': a.is_correct,
                        'was_selected': a.id in selected_ids,
                    }
                    for a in question.answer_ids
                ],
            })

        return {
            'score': score,
            'total_marks': quiz.total_marks,
            'results': results,
        }


class QuizQuestion(models.Model):
    _name = 'quiz.question'
    _description = 'Quiz Question'
    _order = 'quiz_id, sequence, id'

    quiz_id = fields.Many2one('quiz.quiz', string='Quiz', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    question_text = fields.Html(string='Question', required=True, sanitize=True)
    marks = fields.Integer(string='Marks', default=1)
    answer_ids = fields.One2many('quiz.answer', 'question_id', string='Answers')
    correct_answer_count = fields.Integer(
        string='Correct Answers',
        compute='_compute_correct_answer_count',
        store=True,
    )

    @api.depends('answer_ids.is_correct')
    def _compute_correct_answer_count(self):
        for record in self:
            record.correct_answer_count = sum(1 for a in record.answer_ids if a.is_correct)


class QuizAnswer(models.Model):
    _name = 'quiz.answer'
    _description = 'Quiz Answer'
    _order = 'question_id, sequence, id'

    question_id = fields.Many2one('quiz.question', string='Question', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    answer_text = fields.Html(string='Answer', required=True, sanitize=True)
    is_correct = fields.Boolean(string='Correct Answer', default=False)

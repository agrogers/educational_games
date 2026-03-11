from odoo import models, fields, api
from odoo.exceptions import UserError
from markupsafe import escape, Markup
import random
import re
import unicodedata

# Extensible patterns for question and answer line detection.
# Add new compiled regexes to support additional quiz text formats.
_QUESTION_PATTERNS = [
    # "1. What is..." or "1) What is..."
    re.compile(r'^(\d+)[\.)\:]\s+(?P<text>.+)$'),
    # "Question 1: What is..." or "Question 1. What is..."
    re.compile(r'^Question\s+\d+[:\.\)]\s*(?P<text>.+)$', re.IGNORECASE),
]

_ANSWER_PATTERNS = [
    # "A) text", "A. text", "A: text"
    re.compile(r'^(?P<letter>[A-Za-z])[\)\.:]\s+(?P<text>.+)$'),
]

# Prefixes to strip from parsed text.
_QUESTION_PREFIX_RE = re.compile(
    r'^(?:Question\s+\d+[:\.\)]\s*|\d+[:\.\)]\s+)', re.IGNORECASE
)
_ANSWER_PREFIX_RE = re.compile(
    r'^[A-Za-z][\)\.:]\s+'
)


def _normalize_text(text):
    """
    Normalise Unicode characters that are common in text copied from AI tools
    (ChatGPT, NotebookLM, etc.) or word-processors.

    Converts: smart quotes, non-breaking spaces, soft hyphens, zero-width chars,
    en/em dashes, Unicode ellipsis, and leading bullet points.
    """
    text = unicodedata.normalize('NFC', text)
    # Smart / curly quotes → straight quotes
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    # Non-breaking and other special spaces → regular space
    text = re.sub(r'[\u00a0\u202f\u2007\u2009\u3000]', ' ', text)
    # Soft hyphen (invisible, causes regex matching issues)
    text = text.replace('\u00ad', '')
    # Zero-width characters
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    # En dash / em dash / horizontal bar → hyphen
    text = re.sub(r'[\u2013\u2014\u2015]', '-', text)
    # Unicode ellipsis → three dots
    text = text.replace('\u2026', '...')
    # Leading bullet points (common in ChatGPT / NotebookLM lists)
    text = re.sub(r'^[\u2022\u2023\u25e6\u2043\u2219\u00b7]\s*', '', text.strip())
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


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
    header_image = fields.Image(
        string='Header Image',
        max_width=1400,
        max_height=300,
        help='Optional banner image displayed in the quiz header.',
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

    def action_preview_quiz(self):
        """Launch the student quiz view in preview/practice mode."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'action_quiz_game_js',
            'name': self.name,
            'context': {
                'quiz_id': self.id,
            },
        }

    def action_delete_all_questions(self):
        """Delete all questions (and their cascaded answers) for this quiz."""
        for record in self:
            record.question_ids.unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self[:1].id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cleanup_bulk_text(self):
        """
        Normalise the bulk_text field: fix Unicode/special characters from AI
        copy-paste and rebuild with clean, simple HTML structure.

        Bold/italic formatting is preserved so that the import still works
        correctly after a clean-up.
        """
        for record in self:
            if not record.bulk_text or not record.bulk_text.strip():
                raise UserError("Nothing in the text field to clean up.")

            parsed_lines = self._extract_lines_from_html(record.bulk_text)
            if not parsed_lines:
                raise UserError("Could not extract any text from the field.")

            parts = []
            for (text, has_bold, is_italic) in parsed_lines:
                safe = escape(text)
                if is_italic and has_bold:
                    parts.append(Markup('<p><em><strong>{}</strong></em></p>').format(safe))
                elif is_italic:
                    parts.append(Markup('<p><em>{}</em></p>').format(safe))
                elif has_bold:
                    parts.append(Markup('<p><strong>{}</strong></p>').format(safe))
                else:
                    parts.append(Markup('<p>{}</p>').format(safe))

            record.bulk_text = Markup('').join(parts)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self[:1].id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_preview_bulk_text(self):
        """
        Colour-code the bulk_text to show what the importer will parse — without
        creating any records.

        Colour key (visible in the HTML editor):
          · Dark indigo + italic  = question line
          · Green + bold          = correct answer
          · Red                   = other answer option
          · Grey                  = unrecognised line

        The rebuilt HTML also uses semantic <em>/<strong> tags so that
        clicking Import straight after a preview will work correctly.
        """
        _COLORS = {
            # (css-color, bold, italic)
            'question':       ('#1e1b4b', True,  True),
            'answer_correct': ('#15803d', True,  False),
            'answer_option':  ('#9a3412', False, False),
            'unknown':        ('#9ca3af', False, False),
        }

        for record in self:
            if not record.bulk_text or not record.bulk_text.strip():
                raise UserError("Nothing in the text field to preview.")

            parsed_lines = self._extract_lines_from_html(record.bulk_text)
            if not parsed_lines:
                raise UserError("Could not extract any text from the field.")

            categorized = self._preview_parse_lines(parsed_lines)

            parts = []
            prev_category = None
            for (text, category) in categorized:
                # Blank spacer line before each new question for readability
                if category == 'question' and prev_category is not None:
                    parts.append(Markup('<p><br/></p>'))

                color, is_bold, is_italic = _COLORS[category]
                safe = escape(text)

                if is_bold and is_italic:
                    inner = Markup(
                        '<em><strong style="color:{color}">{text}</strong></em>'
                    ).format(color=color, text=safe)
                    parts.append(Markup('<p>{}</p>').format(inner))
                elif is_bold:
                    inner = Markup(
                        '<strong style="color:{color}">{text}</strong>'
                    ).format(color=color, text=safe)
                    parts.append(Markup('<p>{}</p>').format(inner))
                else:
                    parts.append(Markup(
                        '<p style="color:{color}">{text}</p>'
                    ).format(color=color, text=safe))

                prev_category = category

            record.bulk_text = Markup('').join(parts)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self[:1].id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_parse_bulk_text(self):
        """Parse the bulk_text HTML field and auto-create questions and answers."""
        total_q = 0
        total_a = 0
        for record in self:
            if not record.bulk_text or not record.bulk_text.strip():
                raise UserError(
                    "No text to parse. Please paste quiz text into the 'Paste Quiz Text' field first."
                )
            q_count, a_count = self._parse_and_create_questions(record)
            total_q += q_count
            total_a += a_count
            # Intentionally NOT clearing bulk_text so the user can review / re-edit
        if total_q == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Import Failed',
                    'message': (
                        'No questions could be parsed from the pasted text. '
                        'Try the "Clean Up Text" or "Preview Import" buttons first.'
                    ),
                    'type': 'warning',
                    'sticky': True,
                },
            }
        # Reload the form so the Questions tab shows the new records
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self[:1].id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'notification': {
                    'title': 'Import Successful',
                    'message': (
                        f'Imported {total_q} question(s) with {total_a} answer(s). '
                        'The original text has been kept in the field for reference.'
                    ),
                    'type': 'success',
                },
            },
        }

    def _parse_and_create_questions(self, quiz_record):
        """Parse formatted quiz text (HTML or plain) into questions and answers.

        Strategy 1 (primary) – formatting-based:
            Italic line  → new question
            Following non-italic lines → answers (bold = correct)

        Strategy 2 (fallback) – pattern-based:
            Lines matching _QUESTION_PATTERNS → question
            Lines matching _ANSWER_PATTERNS  → answer

        Returns (question_count, answer_count).
        """
        text = quiz_record.bulk_text or ''
        parsed_lines = self._extract_lines_from_html(text)

        # Try formatting-based parsing first
        q_count, a_count = self._parse_by_formatting(quiz_record, parsed_lines)
        if q_count > 0:
            return q_count, a_count

        # Fallback to pattern-based parsing
        return self._parse_by_patterns(quiz_record, parsed_lines)

    def _parse_by_formatting(self, quiz_record, parsed_lines):
        """Strategy 1: italic line = question, subsequent lines = answers, bold = correct."""
        # Check if any italic lines exist; if not this strategy is not applicable
        if not any(is_italic for (_, _, is_italic) in parsed_lines):
            return 0, 0

        current_question = None
        existing_sequences = [q.sequence for q in quiz_record.question_ids]
        q_seq = (max(existing_sequences) + 10) if existing_sequences else 10
        ans_seq = 10
        q_count = 0
        a_count = 0

        for (line_text, has_bold, is_italic) in parsed_lines:
            line_text = line_text.strip()
            if not line_text:
                continue

            if is_italic:
                # New question – strip prefix like "Question 1:"
                clean_q = self._clean_question_text(line_text)
                current_question = self.env['quiz.question'].create({
                    'quiz_id': quiz_record.id,
                    'sequence': q_seq,
                    'question_text': escape(clean_q),
                    'marks': 1,
                })
                q_seq += 10
                ans_seq = 10
                q_count += 1
            elif current_question:
                # Answer line – strip prefix like "A.", bold means correct
                clean_a = self._clean_answer_text(line_text)
                self.env['quiz.answer'].create({
                    'question_id': current_question.id,
                    'sequence': ans_seq,
                    'answer_text': escape(clean_a),
                    'is_correct': has_bold,
                })
                ans_seq += 10
                a_count += 1

        return q_count, a_count

    def _parse_by_patterns(self, quiz_record, parsed_lines):
        """Strategy 2: regex-based question/answer detection."""
        current_question = None
        existing_sequences = [q.sequence for q in quiz_record.question_ids]
        q_seq = (max(existing_sequences) + 10) if existing_sequences else 10
        ans_seq = 10
        q_count = 0
        a_count = 0

        for (line_text, has_bold, _is_italic) in parsed_lines:
            line_text = line_text.strip()
            if not line_text:
                continue

            q_text = self._match_question_line(line_text)
            if q_text is not None:
                current_question = self.env['quiz.question'].create({
                    'quiz_id': quiz_record.id,
                    'sequence': q_seq,
                    'question_text': escape(q_text),
                    'marks': 1,
                })
                q_seq += 10
                ans_seq = 10
                q_count += 1
                continue

            a_result = self._match_answer_line(line_text, has_bold)
            if a_result and current_question:
                answer_text, answer_is_correct = a_result
                self.env['quiz.answer'].create({
                    'question_id': current_question.id,
                    'sequence': ans_seq,
                    'answer_text': escape(answer_text),
                    'is_correct': answer_is_correct,
                })
                ans_seq += 10
                a_count += 1

        return q_count, a_count

    @staticmethod
    def _clean_question_text(text):
        """Strip common question prefixes like 'Question 1:', '1.', '1)' etc."""
        return _QUESTION_PREFIX_RE.sub('', text).strip()

    @staticmethod
    def _clean_answer_text(text):
        """Strip common answer prefixes like 'A.', 'A)', 'A:' etc."""
        return _ANSWER_PREFIX_RE.sub('', text).strip()

    @staticmethod
    def _match_question_line(line_text):
        """Match a question line against _QUESTION_PATTERNS. Returns question text or None."""
        for pattern in _QUESTION_PATTERNS:
            m = pattern.match(line_text)
            if m:
                return m.group('text')
        return None

    @staticmethod
    def _match_answer_line(line_text, line_has_bold):
        """Match an answer line and determine correctness.

        Returns (answer_text, is_correct) or None.
        Detects inline **markdown bold** markers within the answer text.
        """
        for pattern in _ANSWER_PATTERNS:
            m = pattern.match(line_text)
            if m:
                raw_text = m.group('text')
                # Check for inline **bold** markers (e.g. "**Hydraulic action**.")
                bold_match = re.match(r'^\*\*(.+?)\*\*(.?)\s*$', raw_text)
                if bold_match:
                    return (bold_match.group(1) + bold_match.group(2)).strip(), True
                return raw_text, line_has_bold
        return None

    @staticmethod
    def _preview_parse_lines(parsed_lines):
        """
        Categorise parsed lines without creating any database records.

        Returns list of (text, category) where category is one of:
        'question', 'answer_correct', 'answer_option', 'unknown'.
        """
        has_italic = any(is_italic for (_, _, is_italic) in parsed_lines)
        result = []

        if has_italic:
            seen_question = False
            for (text, has_bold, is_italic) in parsed_lines:
                if is_italic:
                    result.append((text, 'question'))
                    seen_question = True
                elif seen_question:
                    result.append((text, 'answer_correct' if has_bold else 'answer_option'))
                else:
                    result.append((text, 'unknown'))
        else:
            has_question = False
            for (text, has_bold, _) in parsed_lines:
                if Quiz._match_question_line(text) is not None:
                    result.append((text, 'question'))
                    has_question = True
                elif has_question:
                    a_result = Quiz._match_answer_line(text, has_bold)
                    if a_result:
                        _, is_correct = a_result
                        result.append((text, 'answer_correct' if is_correct else 'answer_option'))
                    else:
                        result.append((text, 'unknown'))
                else:
                    result.append((text, 'unknown'))

        return result

    @staticmethod
    def _extract_lines_from_html(html_text):
        """
        Return a list of (text, has_bold, is_italic) tuples from HTML quiz content.

        Improvements over v1:
        - Only *leaf* block elements are processed to avoid duplicate text from
          nested containers (e.g. <div><p>…</p></div>).
        - Inline styles (font-weight / font-style on <span>, <p>, etc.) are
          detected in addition to semantic <strong>/<em> tags.
        - All extracted text is passed through _normalize_text() to fix
          copy-paste artefacts from ChatGPT, NotebookLM, etc.

        has_bold:   True when the line contains <strong>/<b>, bold inline style,
                    or ** markdown markers.
        is_italic:  True when the majority of the line's text is in italic tags
                    or has italic inline style.
        """
        lines = []
        BLOCK_TAGS = frozenset(('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'))

        def _elem_is_bold(el):
            if el.tag in ('strong', 'b'):
                return True
            s = el.get('style', '')
            if s and re.search(r'font-weight\s*:\s*(bold|[6-9]00)', s, re.I):
                return True
            return False

        def _elem_is_italic(el):
            if el.tag in ('em', 'i'):
                return True
            s = el.get('style', '')
            if s and re.search(r'font-style\s*:\s*italic', s, re.I):
                return True
            return False

        try:
            from lxml import html as lxml_html
            tree = lxml_html.fragment_fromstring(html_text, create_parent='div')

            for elem in tree.iter():
                if elem.tag not in BLOCK_TAGS:
                    continue
                # Only process leaf blocks — skip elements that contain nested blocks
                if any(child.tag in BLOCK_TAGS for child in elem.iter() if child is not elem):
                    continue

                raw_text = _normalize_text(''.join(elem.itertext()))
                if not raw_text:
                    continue

                total_len = len(raw_text)

                # Detect bold: markdown ** markers take priority
                has_bold = False
                if '**' in raw_text:
                    has_bold = True
                    # Remove ** markers whether inline or wrapping the whole line
                    raw_text = raw_text.replace('**', '').strip()
                else:
                    bold_len = sum(
                        len(_normalize_text(''.join(c.itertext())))
                        for c in elem.iter()
                        if c is not elem and _elem_is_bold(c)
                    )
                    has_bold = bool(bold_len) and bold_len >= total_len * 0.3

                # Detect italic
                italic_len = sum(
                    len(_normalize_text(''.join(c.itertext())))
                    for c in elem.iter()
                    if c is not elem and _elem_is_italic(c)
                )
                is_italic = bool(italic_len) and italic_len >= total_len * 0.5

                if raw_text:
                    lines.append((raw_text, has_bold, is_italic))

        except Exception:
            # Fallback: strip all HTML tags and handle markdown markers
            clean = re.sub(r'<[^>]+>', '\n', html_text)
            for line in clean.split('\n'):
                line = _normalize_text(line)
                if not line:
                    continue
                has_bold = '**' in line
                is_italic = line.startswith('*') and not line.startswith('**')
                # Use replace() consistently with the lxml path
                clean_line = line.replace('**', '').replace('*', '').strip() if (has_bold or is_italic) else line
                clean_line = _normalize_text(clean_line)
                if clean_line:
                    lines.append((clean_line, has_bold, is_italic))
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
                'allow_multiple': question.allow_multiple,
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
            # quiz.id is always a positive integer from the ORM; safe for URL use
            'header_image_url': f'/web/image/quiz.quiz/{quiz.id}/header_image' if quiz.header_image else None,
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
    allow_multiple = fields.Boolean(
        string='Allow Multiple Answers',
        default=False,
        help='If checked, students can select more than one answer.',
    )
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


from odoo import api, fields, models
from odoo.exceptions import UserError
from markupsafe import escape, Markup
import re

from .quiz_utils import (
    _QUESTION_PATTERNS,
    _ANSWER_PATTERNS,
    _QUESTION_PREFIX_RE,
    _ANSWER_PREFIX_RE,
    _MD_BOLD_ITALIC_RE,
    _MD_ITALIC_RE,
    _normalize_text,
)


_MD_PARTIAL_ITALIC_PREFIX_RE = re.compile(r'^\*(?!\*)(?P<italic>[^*]+)\*(?P<suffix>.*)$')


class QuizQuestionImportWizard(models.TransientModel):
    _name = 'quiz.question.import.wizard'
    _description = 'Quiz Questions Import'

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
    import_group = fields.Integer(
        string='Import Group',
        default=lambda self: self._default_import_group(),
        help='Group ID applied to all questions created in this import.',
    )
    subject_ids = fields.Many2many(
        'aps.subject',
        'educational_games_q_import_wizard_subject_rel',
        'wizard_id',
        'subject_id',
        string='Subjects',
        help='These subjects are assigned to every imported question.',
    )
    tag_ids = fields.Many2many(
        'quiz.tag',
        'educational_games_q_import_wizard_tag_rel',
        'wizard_id',
        'tag_id',
        string='Tags',
        help='These tags are assigned to every imported question.',
    )

    @api.model
    def _default_import_group(self):
        max_question = self.env['quiz.question'].search(
            [('import_group', '!=', False)],
            limit=1,
            order='import_group desc',
        )
        return (max_question.import_group or 0) + 1

    def action_cleanup_bulk_text(self):
        self.ensure_one()
        if not self.bulk_text or not self.bulk_text.strip():
            raise UserError("Nothing in the text field to clean up.")

        parsed_lines = self._extract_lines_from_html(self.bulk_text)
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

        self.bulk_text = Markup('').join(parts)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Quiz Questions',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_preview_bulk_text(self):
        self.ensure_one()
        if not self.bulk_text or not self.bulk_text.strip():
            raise UserError("Nothing in the text field to preview.")

        parsed_lines = self._extract_lines_from_html(self.bulk_text)
        if not parsed_lines:
            raise UserError("Could not extract any text from the field.")

        colors = {
            'question': ('#1e1b4b', True, True),
            'answer_correct': ('#15803d', True, False),
            'answer_option': ('#9a3412', False, False),
            'unknown': ('#9ca3af', False, False),
        }

        categorized = self._preview_parse_lines(parsed_lines)
        parts = []
        prev_category = None
        for (text, category) in categorized:
            if category == 'question' and prev_category is not None:
                parts.append(Markup('<p><br/></p>'))

            color, is_bold, is_italic = colors[category]
            safe = escape(text)

            if is_bold and is_italic:
                inner = Markup('<em><strong style="color:{color}">{text}</strong></em>').format(
                    color=color,
                    text=safe,
                )
                parts.append(Markup('<p>{}</p>').format(inner))
            elif is_bold:
                inner = Markup('<strong style="color:{color}">{text}</strong>').format(
                    color=color,
                    text=safe,
                )
                parts.append(Markup('<p>{}</p>').format(inner))
            else:
                parts.append(Markup('<p style="color:{color}">{text}</p>').format(
                    color=color,
                    text=safe,
                ))

            prev_category = category

        self.bulk_text = Markup('').join(parts)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Quiz Questions',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_import_questions(self):
        self.ensure_one()
        if not self.bulk_text or not self.bulk_text.strip():
            raise UserError("No text to parse. Please paste quiz text first.")

        question_count, answer_count = self._parse_and_create_questions()
        if question_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Import Failed',
                    'message': (
                        'No questions could be parsed from the pasted text. '
                        'Try "Clean Up Text" or "Preview Import" first.'
                    ),
                    'type': 'warning',
                    'sticky': True,
                },
            }

        return {
            'type': 'ir.actions.act_window',
            'name': 'Quiz Questions',
            'res_model': 'quiz.question',
            'view_mode': 'list,form',
            'domain': [('import_group', '=', self.import_group)],
            'context': {
                'search_default_import_group': self.import_group,
            },
        }

    def _question_create_vals(self, text, sequence):
        return {
            'sequence': sequence,
            'question_text': escape(text),
            'marks': 1,
            'import_group': self.import_group,
            'tag_ids': [(6, 0, self.tag_ids.ids)],
            'subject_ids': [(6, 0, self.subject_ids.ids)],
        }

    def _parse_and_create_questions(self):
        parsed_lines = self._extract_lines_from_html(self.bulk_text or '')
        question_count, answer_count = self._parse_by_formatting(parsed_lines)
        if question_count > 0:
            return question_count, answer_count
        return self._parse_by_patterns(parsed_lines)

    def _parse_by_formatting(self, parsed_lines):
        if not any(is_italic for (_, _, is_italic) in parsed_lines):
            return 0, 0

        current_question = None
        q_seq = 10
        a_seq = 10
        question_count = 0
        answer_count = 0

        for (line_text, has_bold, is_italic) in parsed_lines:
            line_text = line_text.strip()
            if not line_text:
                continue

            if is_italic:
                clean_q = self._clean_question_text(line_text)
                current_question = self.env['quiz.question'].create(self._question_create_vals(clean_q, q_seq))
                q_seq += 10
                a_seq = 10
                question_count += 1
            elif current_question:
                clean_a = self._clean_answer_text(line_text)
                self.env['quiz.answer'].create({
                    'question_id': current_question.id,
                    'sequence': a_seq,
                    'answer_text': escape(clean_a),
                    'is_correct': has_bold,
                })
                a_seq += 10
                answer_count += 1

        return question_count, answer_count

    def _parse_by_patterns(self, parsed_lines):
        current_question = None
        q_seq = 10
        a_seq = 10
        question_count = 0
        answer_count = 0

        for (line_text, has_bold, _is_italic) in parsed_lines:
            line_text = line_text.strip()
            if not line_text:
                continue

            q_text = self._match_question_line(line_text)
            if q_text is not None:
                current_question = self.env['quiz.question'].create(self._question_create_vals(q_text, q_seq))
                q_seq += 10
                a_seq = 10
                question_count += 1
                continue

            a_result = self._match_answer_line(line_text, has_bold)
            if a_result and current_question:
                answer_text, answer_is_correct = a_result
                self.env['quiz.answer'].create({
                    'question_id': current_question.id,
                    'sequence': a_seq,
                    'answer_text': escape(answer_text),
                    'is_correct': answer_is_correct,
                })
                a_seq += 10
                answer_count += 1

        return question_count, answer_count

    @staticmethod
    def _clean_question_text(text):
        return _QUESTION_PREFIX_RE.sub('', text).strip()

    @staticmethod
    def _clean_answer_text(text):
        return _ANSWER_PREFIX_RE.sub('', text).strip()

    @staticmethod
    def _match_question_line(line_text):
        for pattern in _QUESTION_PATTERNS:
            match = pattern.match(line_text)
            if match:
                return match.group('text')
        return None

    @staticmethod
    def _match_answer_line(line_text, line_has_bold):
        for pattern in _ANSWER_PATTERNS:
            match = pattern.match(line_text)
            if match:
                raw_text = match.group('text')
                bold_match = re.match(r'^\*\*(.+?)\*\*(.?)\s*$', raw_text)
                if bold_match:
                    return (bold_match.group(1) + bold_match.group(2)).strip(), True
                return raw_text, line_has_bold
        return None

    @staticmethod
    def _preview_parse_lines(parsed_lines):
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
                if QuizQuestionImportWizard._match_question_line(text) is not None:
                    result.append((text, 'question'))
                    has_question = True
                elif has_question:
                    a_result = QuizQuestionImportWizard._match_answer_line(text, has_bold)
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
        lines = []
        block_tags = frozenset(('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'))

        def elem_is_bold(el):
            if el.tag in ('strong', 'b'):
                return True
            style_value = el.get('style', '')
            if style_value and re.search(r'font-weight\s*:\s*(bold|[6-9]00)', style_value, re.I):
                return True
            return False

        def elem_is_italic(el):
            if el.tag in ('em', 'i'):
                return True
            style_value = el.get('style', '')
            if style_value and re.search(r'font-style\s*:\s*italic', style_value, re.I):
                return True
            return False

        def append_line_from_segments(segments):
            if not segments:
                return

            raw_text = _normalize_text(''.join(text for (text, _, _) in segments))
            if not raw_text:
                return

            total_len = len(raw_text)
            has_bold = False
            is_italic = False

            bold_italic_match = _MD_BOLD_ITALIC_RE.match(raw_text)
            if bold_italic_match:
                raw_text = bold_italic_match.group(1).strip()
                has_bold = True
                is_italic = True
            else:
                if '**' in raw_text:
                    has_bold = True
                    raw_text = raw_text.replace('**', '').strip()

                partial_italic_match = _MD_PARTIAL_ITALIC_PREFIX_RE.match(raw_text)
                if partial_italic_match:
                    raw_text = _normalize_text(
                        f"{partial_italic_match.group('italic')}{partial_italic_match.group('suffix')}"
                    )
                    is_italic = True

                italic_match = _MD_ITALIC_RE.match(raw_text)
                if italic_match:
                    raw_text = italic_match.group(1).strip()
                    is_italic = True

                if not has_bold:
                    bold_len = sum(
                        len(_normalize_text(text))
                        for (text, segment_is_bold, _) in segments
                        if segment_is_bold and _normalize_text(text)
                    )
                    has_bold = bool(bold_len) and bold_len >= total_len * 0.3

                if not is_italic:
                    italic_len = sum(
                        len(_normalize_text(text))
                        for (text, _, segment_is_italic) in segments
                        if segment_is_italic and _normalize_text(text)
                    )
                    # If any part of the rendered line is italicized, treat the
                    # whole line as the question line and keep trailing plain text.
                    is_italic = bool(italic_len)

            if raw_text:
                lines.append((raw_text, has_bold, is_italic))

        def collect_inline_segments(elem, inherited_bold=False, inherited_italic=False, segments=None):
            if segments is None:
                segments = []

            is_bold = inherited_bold or elem_is_bold(elem)
            is_italic = inherited_italic or elem_is_italic(elem)

            if elem.text:
                segments.append((elem.text, is_bold, is_italic))

            for child in elem:
                if child.tag == 'br':
                    append_line_from_segments(segments)
                    segments.clear()
                else:
                    collect_inline_segments(child, is_bold, is_italic, segments)

                if child.tail:
                    segments.append((child.tail, is_bold, is_italic))

            return segments

        try:
            from lxml import html as lxml_html
            tree = lxml_html.fragment_fromstring(html_text, create_parent='div')

            for elem in tree.iter():
                if elem.tag not in block_tags:
                    continue
                if any(child.tag in block_tags for child in elem.iter() if child is not elem):
                    continue
                segments = collect_inline_segments(elem)
                append_line_from_segments(segments)

        except Exception:
            clean = re.sub(r'<[^>]+>', '\n', html_text)
            for line in clean.split('\n'):
                line = _normalize_text(line)
                if not line:
                    continue
                has_bold = '**' in line
                is_italic = False
                clean_line = line

                bold_italic_match = _MD_BOLD_ITALIC_RE.match(line)
                if bold_italic_match:
                    clean_line = bold_italic_match.group(1).strip()
                    has_bold = True
                    is_italic = True
                elif has_bold:
                    clean_line = line.replace('**', '').strip()
                    italic_match = _MD_ITALIC_RE.match(clean_line)
                    if italic_match:
                        clean_line = italic_match.group(1).strip()
                        is_italic = True
                else:
                    italic_match = _MD_ITALIC_RE.match(line)
                    if italic_match:
                        clean_line = italic_match.group(1).strip()
                        is_italic = True
                    elif line.startswith('*') and not line.startswith('**'):
                        is_italic = True
                        clean_line = line[1:]
                        if clean_line.endswith('*'):
                            clean_line = clean_line[:-1]
                        clean_line = clean_line.strip()

                clean_line = _normalize_text(clean_line)
                if clean_line:
                    lines.append((clean_line, has_bold, is_italic))

        return lines

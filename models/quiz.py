from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError
from odoo.tools import config
from markupsafe import escape, Markup
import base64
from collections import Counter
from datetime import timedelta
import hashlib
import hmac
import json
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

# Plain Markdown detection patterns (used in _extract_lines_from_html).
# _MD_BOLD_ITALIC_RE: ***text*** — whole-line bold+italic wrap
# _MD_ITALIC_RE:      *text*    — whole-line italic wrap (empty *  * is rejected)
_MD_BOLD_ITALIC_RE = re.compile(r'^\*{3}(.+)\*{3}\s*$')
_MD_ITALIC_RE = re.compile(r'^\*([^*]+)\*\s*$')


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
    display_question_count = fields.Integer(
        string='Questions to Show',
        default=0,
        help='Number of questions to display to the student. 0 = show all questions.',
    )
    display_option_count = fields.Integer(
        string='Options to Show',
        default=0,
        help=(
            'Number of answer options to show per question. '
            'The correct answer is always included; remaining slots are filled randomly. '
            '0 = show all options.'
        ),
    )
    allow_resubmission = fields.Boolean(
        string='Allow Resubmission',
        default=False,
        help=(
            'If enabled, students can retake the quiz and save each attempt as '
            'a new submission. The "Submit Quiz" button changes to '
            '"Resubmit this Quiz" on retakes. '
            'If disabled, retakes run in practice mode only (no save).'
        ),
    )
    quiz_url_params = fields.Char(
        string='APEX Game URL',
        compute='_compute_quiz_url_params',
        help=(
            'Copy this into APEX to open this specific quiz. '
            'Format: action:<id>?quiz_id=<id>&…  '
            'Paste it into the resource URL field in the APEX module.'
        ),
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

    @staticmethod
    def _b64url_encode(data):
        return base64.urlsafe_b64encode(data).decode().rstrip('=')

    @staticmethod
    def _b64url_decode(data):
        pad = '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + pad).encode())

    def _sign_quiz_payload(self, payload_json):
        secret = (config.get('database.secret') or self.env.cr.dbname or 'odoo').encode()
        return hmac.new(secret, payload_json.encode(), hashlib.sha256).digest()

    def _build_quiz_token(self, quiz_id, question_count=0, option_count=0, allow_resubmission=False):
        payload = {
            'quiz_id': int(quiz_id),
            'question_count': max(0, int(question_count or 0)),
            'option_count': max(0, int(option_count or 0)),
            'allow_resubmission': bool(allow_resubmission),
        }
        payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        signature = self._sign_quiz_payload(payload_json)
        return f"{self._b64url_encode(payload_json.encode())}.{self._b64url_encode(signature)}"

    def _decode_quiz_token(self, token):
        if not token or '.' not in token:
            return None
        payload_part, sig_part = token.split('.', 1)
        try:
            payload_json = self._b64url_decode(payload_part).decode()
            signature = self._b64url_decode(sig_part)
            expected = self._sign_quiz_payload(payload_json)
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(payload_json)
            return {
                'quiz_id': int(payload.get('quiz_id') or 0),
                'question_count': max(0, int(payload.get('question_count') or 0)),
                'option_count': max(0, int(payload.get('option_count') or 0)),
                'allow_resubmission': bool(payload.get('allow_resubmission')),
            }
        except Exception:
            return None

    @api.depends('display_question_count', 'display_option_count', 'allow_resubmission')
    def _compute_quiz_url_params(self):
        # Resolve the client action ID once for all records in this batch.
        # The format APEX expects is: action:<action_id>?quiz_id=<quiz_id>&quiz_token=<signed>
        try:
            action = self.env.ref('educational_games.action_quiz_game')
            action_id = action.id
        except ValueError:
            # External ID not found — log a warning so it is easy to diagnose
            import logging
            logging.getLogger(__name__).warning(
                "educational_games.action_quiz_game not found; quiz URL will not contain a valid action ID."
            )
            action_id = 'UNKNOWN'

        for record in self:
            # During onchange on unsaved forms, record.id is a NewId placeholder.
            # Only generate a signed URL once we have a real persisted quiz ID.
            quiz_id = record._origin.id or (record.id if isinstance(record.id, int) else 0)
            if not quiz_id:
                record.quiz_url_params = ''
                continue

            token = record._build_quiz_token(
                quiz_id,
                record.display_question_count,
                record.display_option_count,
                record.allow_resubmission,
            )
            parts = [f'quiz_id={quiz_id}', f'quiz_token={token}']
            record.quiz_url_params = f'action:{action_id}?{"&".join(parts)}'

    def action_preview_quiz(self):
        """Launch the student quiz view in preview/practice mode."""
        self.ensure_one()
        quiz_id = self._origin.id or (self.id if isinstance(self.id, int) else 0)
        if not quiz_id:
            raise UserError("Please save the quiz before previewing.")

        # Use a signed token so URL params can configure quiz difficulty without
        # exposing editable plain counts in the browser address bar.
        quiz_params = {
            'quiz_id': quiz_id,
            'quiz_token': self._build_quiz_token(
                quiz_id,
                self.display_question_count,
                self.display_option_count,
                self.allow_resubmission,
            ),
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'action_quiz_game_js',
            'name': self.name,
            # params are put into the URL by the Odoo 18 router, so the quiz
            # can be refreshed without losing the signed quiz context.
            'params': quiz_params,
            # context is kept for compatibility (some callers read it directly).
            'context': quiz_params,
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

    @api.model
    def create_submission_copy(self, source_submission_id):
        """
        Create a copy of an existing aps.resource.submission for resubmission.

        Called by the OWL quiz component (quiz_game.js) when allowResubmission
        is enabled and the student clicks "Resubmit this Quiz".  The copy is
        created using ORM copy() so all required fields are preserved.  The
        due date (whichever field name the APEX module uses) is cleared, and
        score/answer/state are reset to give the student a fresh attempt.

        Returns the ID of the newly created submission.
        """
        Submission = self.env['aps.resource.submission']
        original = Submission.browse(int(source_submission_id))
        if not original.exists():
            raise UserError("Original submission not found.")

        defaults = {
            'score': 0,
            'answer': False,
            'state': 'assigned',
        }
        # Clear the due date on the copy so the student gets an open-ended
        # resubmission with no deadline.  The APEX module (aps_sis) may use
        # different field names across versions; clear every date-like field
        # that exists on the model rather than stopping at the first match.
        for date_field in (
            'date_due',
        ):
            if date_field in Submission._fields:
                defaults[date_field] = False

        new_sub = original.copy(defaults)
        return new_sub.id

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
        is_italic:  True when the majority of the line's text is in italic tags,
                    has italic inline style, or is wrapped in *single asterisks*.

        Supported plain-Markdown inputs (checked before HTML styling):
          *question text*        → italic (question)
          **correct answer**     → bold (correct answer)
          ***bold+italic text*** → bold + italic
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

                # Markdown markers take priority over HTML element styling.
                has_bold = False
                is_italic = False

                # Bold + italic: ***text***
                _m = _MD_BOLD_ITALIC_RE.match(raw_text)
                if _m:
                    raw_text = _m.group(1).strip()
                    has_bold = True
                    is_italic = True
                else:
                    # Bold: ** markers (whole-line wrap or inline occurrences)
                    if '**' in raw_text:
                        has_bold = True
                        raw_text = raw_text.replace('**', '').strip()
                    # Italic: *text* single-asterisk whole-line wrap
                    _m = _MD_ITALIC_RE.match(raw_text)
                    if _m:
                        raw_text = _m.group(1).strip()
                        is_italic = True

                    # Fall back to HTML element inspection when no Markdown found
                    if not has_bold:
                        bold_len = sum(
                            len(_normalize_text(''.join(c.itertext())))
                            for c in elem.iter()
                            if c is not elem and _elem_is_bold(c)
                        )
                        has_bold = bool(bold_len) and bold_len >= total_len * 0.3
                    if not is_italic:
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
                is_italic = False
                clean_line = line
                # Bold + italic: ***text***
                _m = _MD_BOLD_ITALIC_RE.match(line)
                if _m:
                    clean_line = _m.group(1).strip()
                    has_bold = True
                    is_italic = True
                elif has_bold:
                    clean_line = line.replace('**', '').strip()
                    # After stripping **, check if remainder is *text* wrapped
                    _m = _MD_ITALIC_RE.match(clean_line)
                    if _m:
                        clean_line = _m.group(1).strip()
                        is_italic = True
                else:
                    # Italic: *text* whole-line wrap or line that starts with lone *
                    _m = _MD_ITALIC_RE.match(line)
                    if _m:
                        clean_line = _m.group(1).strip()
                        is_italic = True
                    elif line.startswith('*') and not line.startswith('**'):
                        is_italic = True
                        # Strip only the leading * and (if present) trailing *
                        clean_line = line[1:]
                        if clean_line.endswith('*'):
                            clean_line = clean_line[:-1]
                        clean_line = clean_line.strip()
                clean_line = _normalize_text(clean_line)
                if clean_line:
                    lines.append((clean_line, has_bold, is_italic))
        return lines

    @api.model
    def get_quiz_for_student(self, quiz_id, question_count=0, option_count=0, quiz_token=None):
        """
        Return quiz data with randomised answer order for the student view.
        Correct-answer flags are NOT included to prevent client-side cheating;
        validation is performed server-side in submit_quiz_answers.

        :param quiz_id: int – ID of the quiz to load
        :param question_count: int – accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param option_count: int – accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param quiz_token: str – signed token produced by _build_quiz_token().
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        allow_resubmission = False

        # Signed token mode: trust only values encoded in the token.
        if quiz_token:
            token_data = self._decode_quiz_token(quiz_token)
            if not token_data or token_data['quiz_id'] != quiz.id:
                raise UserError("Invalid quiz link.")
            q_limit = token_data['question_count']
            o_limit = token_data['option_count']
            allow_resubmission = token_data['allow_resubmission']
        else:
            # Unsigned URL parameters are intentionally ignored so students
            # cannot lower difficulty by editing query parameters.
            q_limit = 0
            o_limit = 0

        all_questions = list(quiz.question_ids)
        if q_limit > 0 and q_limit < len(all_questions):
            all_questions = random.sample(all_questions, q_limit)

        questions = []
        for question in all_questions:
            all_answers = list(question.answer_ids)

            if o_limit > 0 and o_limit < len(all_answers):
                correct = [a for a in all_answers if a.is_correct]
                wrong = [a for a in all_answers if not a.is_correct]
                # Always keep all correct answers; fill remaining slots with random wrong ones
                keep_wrong = max(0, o_limit - len(correct))
                selected = correct + random.sample(wrong, min(keep_wrong, len(wrong)))
                random.shuffle(selected)
                answers = selected
            else:
                answers = all_answers
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

        displayed_marks = sum(q['marks'] for q in questions)
        is_teacher = (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        )
        return {
            'id': quiz.id,
            'name': quiz.name,
            'total_marks': displayed_marks,
            'allow_resubmission': allow_resubmission,
            # quiz.id is always a positive integer from the ORM; safe for URL use
            'header_image_url': f'/web/image/quiz.quiz/{quiz.id}/header_image' if quiz.header_image else None,
            'questions': questions,
            'is_teacher': is_teacher,
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
        total_marks = 0

        # Only score the questions that the student actually received (keys in answers)
        submitted_ids = {int(k) for k in answers}
        questions_to_score = quiz.question_ids.filtered(lambda q: q.id in submitted_ids) if submitted_ids else quiz.question_ids

        for question in questions_to_score:
            q_id = str(question.id)
            selected_ids = set(int(i) for i in (answers.get(q_id) or []))
            correct_ids = set(question.answer_ids.filtered('is_correct').ids)

            is_correct = bool(correct_ids) and selected_ids == correct_ids
            if is_correct:
                score += question.marks
            total_marks += question.marks

            answer_details = [
                {
                    'id': a.id,
                    'answer_text': a.answer_text or '',
                    'is_correct': a.is_correct,
                    'was_selected': a.id in selected_ids,
                }
                for a in question.answer_ids
            ]
            results.append({
                'question_id': question.id,
                'question_text': question.question_text or '',
                'is_correct': is_correct,
                'correct_answer_ids': list(correct_ids),
                'selected_answer_ids': list(selected_ids),
                'marks': question.marks,
                'answers': answer_details,
            })

        # Persist one quiz.response record for every answer the student selected
        response_vals = []
        for r in results:
            for a in r['answers']:
                if a['was_selected']:
                    response_vals.append({
                        'quiz_id': quiz.id,
                        'question_id': r['question_id'],
                        'answer_id': a['id'],
                        'user_id': self.env.user.id,
                        'is_correct': a['is_correct'],
                    })
        if response_vals:
            self.env['quiz.response'].sudo().create(response_vals)

        # ── Per-question response stats for teacher users ────────────────
        is_teacher = (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        )
        if is_teacher:
            cutoff = fields.Datetime.now() - timedelta(hours=1)
            all_responses = self.env['quiz.response'].search([('quiz_id', '=', quiz.id)])
            recent_responses = all_responses.filtered(
                lambda r: r.create_date and r.create_date >= cutoff
            )
            # Pre-bucket by question so we only loop responses once
            from collections import defaultdict
            all_by_q = defaultdict(list)
            recent_by_q = defaultdict(list)
            for r in all_responses:
                all_by_q[r.question_id.id].append(r.answer_id.id)
            for r in recent_responses:
                recent_by_q[r.question_id.id].append(r.answer_id.id)

            for res in results:
                qid = res['question_id']
                q_all = all_by_q[qid]
                q_recent = recent_by_q[qid]
                total_n = len(q_all)
                recent_n = len(q_recent)
                show_dual = total_n > 0 and recent_n > 0 and recent_n < total_n
                total_by_ans = Counter(q_all)
                recent_by_ans = Counter(q_recent)
                response_stats = {}
                for a in res['answers']:
                    a_id = a['id']
                    a_total = total_by_ans.get(a_id, 0)
                    a_recent = recent_by_ans.get(a_id, 0)
                    response_stats[str(a_id)] = {
                        'total_count': a_total,
                        'total_pct': round(a_total / total_n * 100) if total_n else 0,
                        'recent_count': a_recent,
                        'recent_pct': round(a_recent / recent_n * 100) if recent_n else 0,
                        'show_recent': show_dual,
                    }
                res['response_stats'] = response_stats
                res['show_dual'] = show_dual
                res['total_respondents'] = total_n
                res['recent_respondents'] = recent_n
        # ─────────────────────────────────────────────────────────────────

        return {
            'score': score,
            'total_marks': total_marks,
            'results': results,
            'is_teacher': is_teacher,
        }

    @api.model
    def check_single_question(self, quiz_id, question_id):
        """
        For teachers: reveal the correct answer(s) for a single question without
        submitting the whole quiz.  Only accessible to users in group_aps_teacher
        or group_aps_manager.

        :param quiz_id:     int – ID of the quiz the question belongs to
        :param question_id: int – ID of the question to reveal
        :returns: dict compatible with the per-question entries in submit_quiz_answers
                  results list, with an additional ``selected_answer_ids`` key set
                  from the caller-supplied selections (passed as ``selected_ids``).
        """
        if not (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        ):
            raise AccessError("Only teachers can check individual answers.")

        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        question = self.env['quiz.question'].browse(int(question_id))
        if not question.exists() or question.quiz_id.id != quiz.id:
            raise UserError("Question not found in this quiz.")

        correct_ids = set(question.answer_ids.filtered('is_correct').ids)

        # ── Response statistics ────────────────────────────────────────────
        cutoff = fields.Datetime.now() - timedelta(hours=1)
        all_responses = self.env['quiz.response'].search(
            [('question_id', '=', question.id)]
        )
        recent_responses = all_responses.filtered(
            lambda r: r.create_date and r.create_date >= cutoff
        )
        total_n = len(all_responses)
        recent_n = len(recent_responses)

        # show_dual: True when there are BOTH older and recent responses so we
        # need to display two separate percentages (total vs. last-60-min).
        # If all responses fall within the last hour there is no need for a
        # second figure — they are identical.
        show_dual = total_n > 0 and recent_n > 0 and recent_n < total_n

        # Count selections per answer in a single pass for O(n) complexity
        total_by_ans = Counter(r.answer_id.id for r in all_responses)
        recent_by_ans = Counter(r.answer_id.id for r in recent_responses)

        response_stats = {}
        for a in question.answer_ids:
            a_total = total_by_ans.get(a.id, 0)
            a_recent = recent_by_ans.get(a.id, 0)
            response_stats[str(a.id)] = {
                'total_count': a_total,
                'total_pct': round(a_total / total_n * 100) if total_n else 0,
                'recent_count': a_recent,
                'recent_pct': round(a_recent / recent_n * 100) if recent_n else 0,
                'show_recent': show_dual,
            }
        # ──────────────────────────────────────────────────────────────────

        return {
            'question_id': question.id,
            'question_text': question.question_text or '',
            'correct_answer_ids': list(correct_ids),
            'marks': question.marks,
            'answers': [
                {
                    'id': a.id,
                    'answer_text': a.answer_text or '',
                    'is_correct': a.is_correct,
                }
                for a in question.answer_ids
            ],
            'response_stats': response_stats,
            'show_dual': show_dual,
            'total_respondents': total_n,
            'recent_respondents': recent_n,
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


class QuizResponse(models.Model):
    """
    Records each answer a student selects when submitting a quiz.

    One record is created per selected answer per submission, so a student who
    picks three options for a multi-answer question produces three rows.
    ``is_correct`` reflects whether that specific answer option is a correct
    one (copied from ``quiz.answer.is_correct`` at submission time).
    """
    _name = 'quiz.response'
    _description = 'Quiz Question Response'
    _order = 'create_date desc, id desc'

    quiz_id = fields.Many2one(
        'quiz.quiz', string='Quiz', required=True, ondelete='cascade', index=True,
    )
    question_id = fields.Many2one(
        'quiz.question', string='Question', required=True, ondelete='cascade', index=True,
    )
    answer_id = fields.Many2one(
        'quiz.answer', string='Selected Answer', required=True, ondelete='cascade',
    )
    user_id = fields.Many2one(
        'res.users', string='Student', required=True,
        default=lambda self: self.env.user, index=True,
    )
    is_correct = fields.Boolean(
        string='Correct Answer',
        help='Whether the selected answer option is a correct answer.',
    )


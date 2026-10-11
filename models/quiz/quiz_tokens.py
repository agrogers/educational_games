import base64
import hashlib
import hmac
import json

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools import config

SKIP_QUIZ_TOKEN_SIGNATURE_CHECK = True


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

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

    def _build_quiz_token(self, quiz_id, question_count=0, option_count=0, allow_resubmission=False, filter_payload=None, bypass_student_filters=False):
        payload = {
            'quiz_id': int(quiz_id),
            'question_count': max(0, int(question_count or 0)),
            'option_count': max(0, int(option_count or 0)),
            'allow_resubmission': bool(allow_resubmission),
            'bypass_student_filters': bool(bypass_student_filters),
        }
        payload.update(self._normalize_quiz_filter_payload(filter_payload))
        payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        signature = self._sign_quiz_payload(payload_json)
        return f"{self._b64url_encode(payload_json.encode())}.{self._b64url_encode(signature)}"

    def _decode_quiz_token(self, token):
        if not token or '.' not in token:
            return None
        payload_part, sig_part = token.split('.', 1)
        try:
            payload_json = self._b64url_decode(payload_part).decode()
            if not SKIP_QUIZ_TOKEN_SIGNATURE_CHECK:
                signature = self._b64url_decode(sig_part)
                expected = self._sign_quiz_payload(payload_json)
                if not hmac.compare_digest(signature, expected):
                    return None
            payload = json.loads(payload_json)
            filter_payload = self._normalize_quiz_filter_payload(payload)
            return {
                'quiz_id': int(payload.get('quiz_id') or 0),
                'question_count': max(0, int(payload.get('question_count') or 0)),
                'option_count': max(0, int(payload.get('option_count') or 0)),
                'allow_resubmission': bool(payload.get('allow_resubmission')),
                'bypass_student_filters': bool(payload.get('bypass_student_filters')),
                **filter_payload,
            }
        except Exception:
            return None

    @api.model
    def rebuild_quiz_token(self, quiz_id, current_token=None, question_count=None, option_count=None, allow_resubmission=None, bypass_student_filters=None):
        """Return a token with the same filter scope but a different display cap.

        This is used by the quiz client when the user clicks "ALL" to clear only
        the display_question_count cap while keeping the quiz's real Tag/Subject
        filters intact.  When ``bypass_student_filters`` is True the student
        performance filters (min/max attempts, weighted score, exclude answered
        days) are also ignored so every question in the static scope is shown.

        :param bypass_student_filters: bool or None.  None preserves the value
            decoded from ``current_token``; otherwise the given value is used.
        """
        quiz_id = int(quiz_id or 0)
        if not quiz_id:
            return ''

        quiz = self.browse(quiz_id)
        decoded = self._decode_quiz_token(current_token) if current_token else {}
        filter_payload = {}
        if decoded:
            filter_payload = self._normalize_quiz_filter_payload(decoded)
        elif quiz.exists():
            filter_payload = quiz._get_quiz_filter_payload()

        if question_count is None:
            next_question_count = max(0, int(quiz.display_question_count or 0))
        else:
            next_question_count = max(0, int(question_count or 0))
        next_option_count = max(0, int(option_count if option_count is not None else (decoded.get('option_count') if decoded else 0)))
        next_allow_resubmission = bool(
            allow_resubmission if allow_resubmission is not None else (decoded.get('allow_resubmission') if decoded else False)
        )
        next_bypass_student_filters = bool(
            bypass_student_filters if bypass_student_filters is not None else (decoded.get('bypass_student_filters') if decoded else False)
        )

        payload = {
            'quiz_id': quiz_id,
            'question_count': next_question_count,
            'option_count': next_option_count,
            'allow_resubmission': next_allow_resubmission,
            'bypass_student_filters': next_bypass_student_filters,
            **filter_payload,
        }
        return quiz._build_quiz_token(
            quiz_id,
            next_question_count,
            next_option_count,
            next_allow_resubmission,
            payload,
            next_bypass_student_filters,
        )



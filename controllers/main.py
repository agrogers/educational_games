import re

from odoo import http
from odoo.http import request

class EducationalGamesController(http.Controller):

    @http.route(
        '/educational_games/memory_reveal/image/<int:quiz_id>',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def memory_reveal_image(self, quiz_id, **kwargs):
        """Serve the image embedded in a Memory Reveal quiz.

        Pasted/uploaded editor images may be attached to another model, so
        the original /web/image URL can fail the student's attachment access
        check even when the student may read the quiz itself.
        """
        quiz = request.env['quiz.quiz'].browse(quiz_id)
        if not quiz.exists() or quiz.quiz_type != 'memory_reveal':
            return request.not_found()

        quiz.check_access_rights('read')
        quiz.check_access_rule('read')

        match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']',
            quiz.image_content or '',
            flags=re.IGNORECASE,
        )
        if not match:
            return request.not_found()

        image_url = match.group(1)
        attachment_match = re.search(
            r'/web/image/(?:ir\.attachment/)?(\d+)(?:[-/]|$)',
            image_url,
            flags=re.IGNORECASE,
        )
        if not attachment_match:
            # Odoo's HTML editor can store the short hash URL form, such as
            # /web/image/1050040-7cdf9399/energy.webp.
            attachment_match = re.search(
                r'/web/image/(\d+)-[^/?]+(?:[/?]|$)',
                image_url,
                flags=re.IGNORECASE,
            )
        if not attachment_match:
            return request.not_found()

        attachment = request.env['ir.attachment'].sudo().browse(
            int(attachment_match.group(1))
        )
        if not attachment.exists() or not attachment.raw:
            return request.not_found()

        return request.make_response(
            attachment.raw,
            headers=[
                ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                ('Content-Disposition', 'inline'),
                ('Cache-Control', 'private, max-age=3600'),
            ],
        )

    @http.route('/educational_games/dashboard', type='http', auth='user')
    def dashboard(self, **kwargs):
        return request.render('educational_games.EducationalGamesDashboard')

    @http.route('/educational_games/glowing_circle', type='http', auth='user')
    def glowing_circle(self, **kwargs):
        return request.render('educational_games.EducationalGamesGlowingCircle')

    @http.route('/educational_games/click_game', type='http', auth='user')
    def click_game(self, **kwargs):
        return request.render('educational_games.ClickGame')

    @http.route('/educational_games/binary_adder', type='http', auth='public')
    def binary_adder(self, **kwargs):
        return request.render('educational_games.binary_adder_template')
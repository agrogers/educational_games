from odoo import http
from odoo.http import request

class EducationalGamesController(http.Controller):

    @http.route('/educational_games/dashboard', type='http', auth='user')
    def dashboard(self, **kwargs):
        return request.render('educational_games.EducationalGamesDashboard')

    @http.route('/educational_games/glowing_circle', type='http', auth='user')
    def glowing_circle(self, **kwargs):
        return request.render('educational_games.EducationalGamesGlowingCircle')

    @http.route('/educational_games/click_game', type='http', auth='user')
    def click_game(self, **kwargs):
        return request.render('educational_games.ClickGame')
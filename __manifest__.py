{
    'name': 'Educational Games',
    'version': '18.0.1.0.2',
    'category': 'Education',
    'summary': 'Educational games for learning English grammar',
    'description': 'A collection of educational games to help students learn English grammar concepts.',
    'author': 'Your Name',
    'website': '',
    'depends': ['base', 'web'],
    'data': [
        'views/actions.xml',
        'views/educational_games_menu.xml',
        'views/educational_games_views.xml',
        'views/glowing_circle_client_action.xml',
        'views/glowing_circle_client_action_template.xml',
        'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_frontend': [
            'educational_games/static/src/js/click_game.js',
            'educational_games/static/src/css/educational_games.css',
        ],
        'web.assets_backend': [
            'educational_games/static/src/js/game_action.js',
            'educational_games/static/src/xml/game_action.xml',
        ],
    },
    'installable': True,
    'application': True,
}
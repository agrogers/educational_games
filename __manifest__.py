{
    'name': 'Educational Games',
    'version': '18.0.1.1.2',
    'category': 'Education',
    'summary': 'Educational games for learning English grammar',
    'description': 'A collection of educational games to help students learn English grammar concepts.',
    'author': 'Your Name',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail', 'bus', 'aps_sis', 'aui_enhancements'],
    'data': [
        'security/ir.model.access.csv',
        'views/quiz_actions.xml',
        # live_game_views.xml defines action_live_game_session_from_quiz,
        # which quiz_views.xml references via %(xml_id)d — it must load first.
        'views/live_game_views.xml',
        'views/live_game_templates.xml',
        'views/quiz_views.xml',
        'views/actions.xml',
        'views/educational_games_menu.xml',
        'views/educational_games_views.xml',
        # 'views/html_iframe_wrapper.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'educational_games/static/src/css/educational_games.css',
            'educational_games/static/src/js/dashboard/dashboard.js',
            'educational_games/static/src/js/dashboard/dashboard_action.xml',
            'educational_games/static/src/js/binary_conversions/binary_conversions.js',
            'educational_games/static/src/js/binary_conversions/binary_conversions_action.xml',
            # Shared utility: ORM write + notifications for aps.resource.submission.
            # Must be listed before any game/quiz JS that imports from it.
            'educational_games/static/src/js/utils/aps_submission.js',
            'educational_games/static/src/js/lonely_s/lonely_s_game.js',
            'educational_games/static/src/js/lonely_s/lonely_s_game_action.xml',
            # 'educational_games/static/src/js/binaryadder2.js',
            # 'educational_games/static/src/xml/binaryadder2_action.xml',
            'educational_games/static/src/js/html_game_wrapper.js',
            'educational_games/static/src/xml/html_game_wrapper.xml',
            'educational_games/static/src/js/game_action.js',
            'educational_games/static/src/xml/game_action.xml',
            'educational_games/static/src/js/quiz/quiz_game.js',
            'educational_games/static/src/js/quiz/quiz_game_action.xml',
            # Memory Reveal: teacher setup viewer
            'educational_games/static/src/js/memory_reveal/memory_reveal_setup.js',
            'educational_games/static/src/xml/memory_reveal_setup.xml',
            # Memory Reveal: student game viewer
            'educational_games/static/src/js/memory_reveal/memory_reveal_game.js',
            'educational_games/static/src/xml/memory_reveal_game.xml',
        ],
        # Live realtime games run on standalone frontend pages
        # (/educational_games/live/...) rendered via web.frontend_layout, so
        # their assets go in the frontend bundle.  Order matters: shared
        # modules (live_bus, track) must come before the components that
        # import them.
        'web.assets_frontend': [
            'educational_games/static/src/js/live/live_game.css',
            'educational_games/static/src/js/live/live_bus.js',
            'educational_games/static/src/js/live/track.js',
            'educational_games/static/src/js/live/host_console.js',
            'educational_games/static/src/js/live/host_console.xml',
            'educational_games/static/src/js/live/student_player.js',
            'educational_games/static/src/js/live/student_player.xml',
            'educational_games/static/src/js/live/main.js',
        ],
    },
    'installable': True,
    'application': True,
}
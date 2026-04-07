def migrate(cr, version):
    """Populate quiz_quiz_question_rel M2M table from existing quiz_id FK on quiz_question.

    Prior to 18.0.1.1.0, quiz membership was stored as a Many2one (quiz_id) on
    quiz.question.  This migration copies those rows into the new Many2many
    relation table so existing questions remain visible in their quizzes.
    """
    cr.execute("""
        INSERT INTO quiz_quiz_question_rel (quiz_id, question_id)
        SELECT quiz_id, id
        FROM quiz_question
        WHERE quiz_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

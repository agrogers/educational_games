def migrate(cr, version):
    """Clean up stored columns that are no longer needed.

    quiz_quiz.question_count and quiz_quiz.total_marks changed from
    store=True to store=False in this version.  Their database columns
    are now unused and can be safely dropped.
    """
    cr.execute("""
        ALTER TABLE quiz_quiz
            DROP COLUMN IF EXISTS question_count,
            DROP COLUMN IF EXISTS total_marks
    """)

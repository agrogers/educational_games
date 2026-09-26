from odoo import _
from odoo.exceptions import AccessError, UserError

from odoo.addons.aps_ai.models.tool_handlers import register_ai_tool_handler


def _check_quiz_question_tool_user(env):
    user = env.user
    if not (
        user.has_group('aps_sis.group_aps_teacher')
        or user.has_group('aps_sis.group_aps_manager')
        or user.has_group('base.group_system')
    ):
        raise AccessError(_('Only APEX teachers and managers can use quiz question tools.'))


@register_ai_tool_handler('find_likely_duplicate_quiz_questions')
def find_likely_duplicate_quiz_questions(env, _tool, arguments):
    _check_quiz_question_tool_user(env)
    return env['quiz.question.embedding.service']._find_likely_duplicates(
        question_id=arguments['question_id'],
        quiz_id=arguments.get('quiz_id'),
        limit=arguments.get('limit', 10),
    )


@register_ai_tool_handler('merge_confirmed_quiz_question_pair')
def merge_confirmed_quiz_question_pair(env, _tool, arguments):
    _check_quiz_question_tool_user(env)
    keep_id = arguments['keep_question_id']
    duplicate_id = arguments['merge_question_id']
    if keep_id == duplicate_id:
        raise UserError(_('Choose two different questions to merge.'))

    Question = env['quiz.question']
    questions = Question.search([('id', 'in', [keep_id, duplicate_id])])
    if set(questions.ids) != {keep_id, duplicate_id}:
        raise UserError(_('One or both questions are missing or are not accessible.'))
    questions.check_access('write')

    keep = Question.browse(keep_id)
    duplicate = Question.browse(duplicate_id)
    response_count = env['quiz.response'].search_count([
        ('question_id', '=', duplicate.id),
    ])
    answer_count = len(keep.answer_ids)
    with env.cr.savepoint():
        Question.browse([keep_id, duplicate_id]).action_merge_questions()
    return {
        'status': 'merged',
        'kept_question_id': keep_id,
        'removed_question_id': duplicate_id,
        'kept_answer_option_count': answer_count,
        'responses_remapped': response_count,
    }
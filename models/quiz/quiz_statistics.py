import re
from collections import Counter
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    @api.model
    def get_dashboard_data(self, date_range='30d'):
        """Return aggregated data for the educational games dashboard.

        :param date_range: one of ``today``, ``7d``, ``14d``, ``30d``, ``90d``, ``365d``, ``all``
        """

        def _strip_html(html_str):
            if not html_str:
                return ''
            return re.sub(r'<[^>]+>', '', str(html_str)).strip()

        QuizQuestion = self.env['quiz.question'].sudo()
        QuizResponse = self.env['quiz.response'].sudo()

        now = fields.Datetime.now()
        range_days_map = {
            'today': 0,
            '7d': 7,
            '14d': 14,
            '30d': 30,
            '90d': 90,
            '365d': 365,
            'all': None,
        }
        range_key = date_range if date_range in range_days_map else '30d'
        days = range_days_map.get(range_key)

        date_from = None
        if days is not None:
            if days == 0:
                date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                date_from = now - timedelta(days=days)

        quizzes_domain = [('create_date', '>=', date_from)] if date_from else []
        questions_domain = [('create_date', '>=', date_from)] if date_from else []
        responses_domain = [('create_date', '>=', date_from)] if date_from else []

        # === Overview stats ===
        total_quizzes = self.sudo().search_count(quizzes_domain)
        total_questions = QuizQuestion.search_count(questions_domain)
        total_responses = QuizResponse.search_count(responses_domain)

        student_groups = QuizResponse.read_group(
            domain=responses_domain + [('user_id', '!=', False)],
            fields=['user_id'],
            groupby=['user_id'],
        )
        active_students = len(student_groups)

        # === Recently created quizzes (last 10) ===
        recent_quizzes_records = self.sudo().search(
            quizzes_domain, order='create_date desc', limit=10
        )
        recent_quizzes = [
            {
                'id': q.id,
                'name': q.name,
                'question_count': len(q.question_ids),
                'create_date': (
                    fields.Datetime.to_string(q.create_date) if q.create_date else ''
                ),
            }
            for q in recent_quizzes_records
        ]

        # === Recently active quizzes (10 quizzes with most recent responses) ===
        recent_resp = QuizResponse.search(responses_domain, order='create_date desc', limit=500)
        seen_quiz_ids = []
        seen_set = set()
        quiz_resp_data = {}
        for r in recent_resp:
            qid = r.quiz_id.id
            if not qid:
                continue
            if qid not in seen_set:
                seen_set.add(qid)
                seen_quiz_ids.append(qid)
                quiz_resp_data[qid] = {
                    'last_activity': (
                        fields.Datetime.to_string(r.create_date) if r.create_date else ''
                    ),
                    'student_ids': set(),
                    'response_count': 0,
                }
            if r.user_id:
                quiz_resp_data[qid]['student_ids'].add(r.user_id.id)
            quiz_resp_data[qid]['response_count'] += 1

        recent_activity_quiz_ids = seen_quiz_ids[:10]
        recent_activity_quizzes = self.sudo().browse(recent_activity_quiz_ids)
        recent_activity = []
        for q in recent_activity_quizzes:
            data = quiz_resp_data.get(q.id, {})
            recent_activity.append({
                'id': q.id,
                'name': q.name,
                'last_activity': data.get('last_activity', ''),
                'student_count': len(data.get('student_ids', set())),
                'response_count': data.get('response_count', 0),
            })

        # === Struggling questions: most-attempted questions with lowest % correct ===
        if date_from:
            grouped_by_question = QuizResponse.read_group(
                domain=responses_domain + [('question_id', '!=', False)],
                fields=['question_id', 'is_correct'],
                groupby=['question_id', 'is_correct'],
                lazy=False,
            )
            question_stats = {}
            for row in grouped_by_question:
                q_ref = row.get('question_id')
                if not q_ref:
                    continue
                qid = q_ref[0]
                stat = question_stats.setdefault(qid, {'attempt_count': 0, 'correct_count': 0})
                count = row.get('__count', 0)
                stat['attempt_count'] += count
                if row.get('is_correct'):
                    stat['correct_count'] += count

            sorted_qids = sorted(
                question_stats.keys(),
                key=lambda qid: (
                    round((question_stats[qid]['correct_count'] / question_stats[qid]['attempt_count']) * 100)
                    if question_stats[qid]['attempt_count'] else 100,
                    -question_stats[qid]['attempt_count'],
                ),
            )[:10]

            question_map = {
                q.id: q for q in QuizQuestion.browse(sorted_qids).exists()
            }
            struggling_questions = []
            for qid in sorted_qids:
                question = question_map.get(qid)
                if not question:
                    continue
                attempts = question_stats[qid]['attempt_count']
                correct = question_stats[qid]['correct_count']
                pct_correct = round((correct / attempts) * 100) if attempts else 0
                struggling_questions.append({
                    'id': question.id,
                    'question_text': _strip_html(question.question_text),
                    'attempt_count': attempts,
                    'pct_correct_all': pct_correct,
                })
        else:
            struggling_records = QuizQuestion.search(
                [('attempt_count', '>', 0)],
                order='pct_correct_all asc, attempt_count desc',
                limit=10,
            )
            struggling_questions = [
                {
                    'id': q.id,
                    'question_text': _strip_html(q.question_text),
                    'attempt_count': q.attempt_count,
                    'pct_correct_all': q.pct_correct_all,
                }
                for q in struggling_records
            ]

        # === Student leaderboard: rank by distinct quizzes taken ===
        user_quiz_rows = QuizResponse.read_group(
            domain=responses_domain + [('user_id', '!=', False)],
            fields=['user_id', 'quiz_id'],
            groupby=['user_id', 'quiz_id'],
            lazy=False,
        )
        user_stats = {}
        for row in user_quiz_rows:
            if not row.get('user_id') or not row.get('quiz_id'):
                continue
            uid = row['user_id'][0]
            uname = row['user_id'][1]
            if uid not in user_stats:
                user_stats[uid] = {
                    'id': uid,
                    'name': uname,
                    'quiz_count': 0,
                    'response_count': 0,
                    'correct_count': 0,
                    'average_score': 0,
                }
            user_stats[uid]['quiz_count'] += 1
            user_stats[uid]['response_count'] += row.get('__count', 0)

        user_correct_rows = QuizResponse.read_group(
            domain=responses_domain + [('user_id', '!=', False), ('is_correct', '=', True)],
            fields=['user_id'],
            groupby=['user_id'],
            lazy=False,
        )
        for row in user_correct_rows:
            if not row.get('user_id'):
                continue
            uid = row['user_id'][0]
            if uid in user_stats:
                user_stats[uid]['correct_count'] = row.get('__count', 0)

        for stat in user_stats.values():
            total_responses_for_user = stat.get('response_count', 0)
            if total_responses_for_user:
                stat['average_score'] = round((stat.get('correct_count', 0) / total_responses_for_user) * 100, 1)
            else:
                stat['average_score'] = 0
        leaderboard = sorted(
            user_stats.values(),
            key=lambda x: (x['quiz_count'], x['average_score'], x['response_count']),
            reverse=True,
        )[:10]

        return {
            'date_range': range_key,
            'stats': {
                'total_quizzes': total_quizzes,
                'total_questions': total_questions,
                'total_responses': total_responses,
                'active_students': active_students,
            },
            'recent_quizzes': recent_quizzes,
            'recent_activity': recent_activity,
            'struggling_questions': struggling_questions,
            'leaderboard': leaderboard,
        }

    @api.model
    def check_single_question(self, quiz_id, question_id):
        """
        For teachers: reveal the correct answer(s) for a single question without
        submitting the whole quiz.  Only accessible to users in group_aps_teacher
        or group_aps_manager.

        :param quiz_id:     int â€“ ID of the quiz the question belongs to
        :param question_id: int â€“ ID of the question to reveal
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
        if not question.exists() or question.id not in quiz.question_ids.ids:
            raise UserError("Question not found in this quiz.")

        correct_ids = set(question.answer_ids.filtered('is_correct').ids)

        # â”€â”€ Response statistics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        # second figure â€” they are identical.
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
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    @api.model
    def get_quiz_student_statistics(self, quiz_id):
        """Return per-student progress summary data for all students who have
        answered at least one question in this quiz.

        Returns a list sorted by student name, where each entry contains:
        - user_id, user_name
        - progress_summary: same structure as _build_student_progress_summary
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        responses = self.env['quiz.response'].sudo().search(
            [('quiz_id', '=', quiz.id)],
        )
        users = responses.mapped('user_id')

        filter_payload = quiz._get_quiz_filter_payload()

        result = []
        for user in users:
            student_stats = quiz._get_student_question_attempt_stats(quiz.question_ids, user)
            progress = quiz._build_student_progress_summary(quiz, filter_payload, student_stats)
            result.append({
                'user_id': user.id,
                'user_name': user.name or '',
                'progress_summary': progress,
            })

        result.sort(key=lambda x: (x['user_name'] or '').lower())
        return result

    @api.model
    def get_student_progress_summaries(self, quiz_ids):
        """Return mastery summaries for the current user, keyed by quiz ID."""
        requested_ids = []
        for value in quiz_ids or []:
            try:
                quiz_id = int(value)
            except (TypeError, ValueError):
                continue
            if quiz_id > 0 and quiz_id not in requested_ids:
                requested_ids.append(quiz_id)

        summaries = {}
        for quiz in self.browse(requested_ids).exists():
            student_stats = quiz._get_student_question_attempt_stats(
                quiz.question_ids,
                self.env.user,
            )
            summaries[str(quiz.id)] = quiz._build_student_progress_summary(
                quiz,
                quiz._get_quiz_filter_payload(),
                student_stats,
            )
        return summaries



import random
import uuid
from collections import Counter
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class Quiz(models.Model):
    _inherit = 'quiz.quiz'

    @api.model
    def get_quiz_for_student(self, quiz_id, question_count=0, option_count=0, quiz_token=None):
        """
        Return quiz data with randomised answer order for the student view.
        Correct-answer flags are NOT included to prevent client-side cheating;
        validation is performed server-side in submit_quiz_answers.

        :param quiz_id: int â€“ ID of the quiz to load
        :param question_count: int â€“ accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param option_count: int â€“ accepted only for backward compatibility.
            Ignored unless quiz_token is valid.
        :param quiz_token: str â€“ signed token produced by _build_quiz_token().
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        allow_resubmission = False
        bypass_student_filters = False

        # Signed token mode: trust only values encoded in the token.
        if quiz_token:
            token_data = self._decode_quiz_token(quiz_token)
            if not token_data or token_data['quiz_id'] != quiz.id:
                raise UserError("Invalid quiz link.")
            q_limit = token_data['question_count']
            o_limit = token_data['option_count']
            allow_resubmission = token_data['allow_resubmission']
            bypass_student_filters = token_data['bypass_student_filters']
            filter_payload = self._normalize_quiz_filter_payload(token_data)
        else:
            # Unsigned URL parameters are intentionally ignored so students
            # cannot lower difficulty by editing query parameters.
            q_limit = 0
            o_limit = 0
            filter_payload = self._normalize_quiz_filter_payload({})

        rng = random.SystemRandom()

        effective_questions = quiz.question_ids
        all_questions = list(effective_questions)

        student_stats = self._get_student_question_attempt_stats(effective_questions, self.env.user)
        progress_summary = self._build_student_progress_summary(quiz, filter_payload, student_stats)

        if bypass_student_filters:
            # "ALL" mode: ignore every student-based filter (min/max attempts,
            # weighted score, student attempts, exclude answered days) and show
            # every question in the static scope (tags / exclude tags / subjects).
            all_questions = [
                question for question in all_questions
                if self._question_matches_static_scope(question, filter_payload)
            ]
        else:
            all_questions = [
                question for question in all_questions
                if self._question_matches_filter_payload(question, filter_payload, student_stats)
            ]

        if q_limit > 0 and q_limit < len(all_questions):
            all_questions = rng.sample(all_questions, q_limit)

        # Pre-fetch incorrect response counts for every question in this quiz so
        # we can pick the "most-often-wrong" distractor without N+1 queries.
        # result: {question_id: {answer_id: count, ...}, ...}
        wrong_response_counts = {}
        if o_limit > 0:
            question_ids = [q.id for q in all_questions]
            wrong_responses = self.env['quiz.response'].sudo().read_group(
                domain=[
                    ('question_id', 'in', question_ids),
                    ('is_correct', '=', False),
                ],
                fields=['question_id', 'answer_id'],
                groupby=['question_id', 'answer_id'],
                lazy=False,
            )
            for row in wrong_responses:
                qid = row['question_id'][0]
                aid = row['answer_id'][0]
                wrong_response_counts.setdefault(qid, {})[aid] = row['__count']

        questions = []
        for question in all_questions:
            all_answers = list(question.answer_ids)
            question_student_stats = student_stats.get(
                question.id,
                {'attempt_count': 0, 'weighted_score_pct': None},
            )

            if o_limit > 0 and o_limit < len(all_answers):
                correct = [a for a in all_answers if a.is_correct]
                wrong = [a for a in all_answers if not a.is_correct]

                # Pin the most-often-selected incorrect answer as a guaranteed distractor
                counts = wrong_response_counts.get(question.id, {})
                if counts and wrong:
                    top_wrong = max(wrong, key=lambda a: counts.get(a.id, 0))
                    remaining_wrong = [a for a in wrong if a is not top_wrong]
                    pinned_wrong = [top_wrong]
                else:
                    pinned_wrong = []
                    remaining_wrong = wrong

                # Fill remaining slots with random wrong answers
                keep_wrong = max(0, o_limit - len(correct) - len(pinned_wrong))
                selected = correct + pinned_wrong + rng.sample(remaining_wrong, min(keep_wrong, len(remaining_wrong)))
                rng.shuffle(selected)
                answers = selected
            else:
                answers = all_answers
                rng.shuffle(answers)

            answers_list = []
            for a in answers:
                ans_data = {
                    'id': a.id,
                    'answer_text': a.answer_text or '',
                }
                if quiz.quiz_type == 'memory_reveal':
                    ans_data['marks'] = a.marks
                answers_list.append(ans_data)

            q_data = {
                'id': question.id,
                'question_text': question.question_text or '',
                'marks': question.marks,
                'allow_multiple': question.allow_multiple,
                'student_attempt_count': question_student_stats['attempt_count'],
                'student_weighted_score_pct': round(question_student_stats['weighted_score_pct'] or 0),
                'answers': answers_list,
            }
            if quiz.quiz_type == 'memory_reveal':
                q_data['region'] = {
                    'x1': question.region_x1,
                    'y1': question.region_y1,
                    'x2': question.region_x2,
                    'y2': question.region_y2,
                }
                q_data['region_name'] = question.question_text or ''
            questions.append(q_data)

        displayed_marks = sum(q['marks'] for q in questions)
        is_teacher = (
            self.env.user.has_group('aps_sis.group_aps_teacher') or
            self.env.user.has_group('aps_sis.group_aps_manager')
        )
        result = {
            'id': quiz.id,
            'name': quiz.name,
            'quiz_type': quiz.quiz_type,
            'total_marks': displayed_marks,
            'allow_resubmission': allow_resubmission,
            'filter_summary': quiz._build_filter_summary(filter_payload),
            'student_progress_summary': progress_summary,
            # quiz.id is always a positive integer from the ORM; safe for URL use
            'header_image_url': (
                f'/web/image/quiz.quiz/{quiz.id}/header_image'
                if quiz.header_image
                else '/educational_games/static/src/img/quiz_bg.jpg'
            ),
            'questions': questions,
            'is_teacher': is_teacher,
        }
        if quiz.quiz_type == 'memory_reveal':
            result['image_url'] = self.env['quiz.quiz'].get_memory_reveal_image_url(quiz.id) or ''
        return result

    @api.model
    def submit_quiz_answers(self, quiz_id, answers, quiz_token=None):
        """
        Validate answers server-side and return scoring details.

        :param quiz_id: int â€“ ID of the quiz being submitted
        :param answers: dict[str, list[int]] â€“ mapping of str(question_id) to
                        list of selected answer IDs
        :returns: dict with keys score, total_marks, results
        """
        quiz = self.browse(int(quiz_id))
        if not quiz.exists():
            raise UserError("Quiz not found.")

        token_data = self._decode_quiz_token(quiz_token) if quiz_token else None
        filter_payload = self._normalize_quiz_filter_payload(token_data or {})
        has_active_filters = any([
            token_data and token_data.get('question_count'),
            token_data and token_data.get('option_count'),
            filter_payload['filter_tag_ids'],
            filter_payload['filter_exclude_tag_ids'],
            filter_payload['filter_subject_ids'],
            filter_payload['filter_min_attempts'] is not None,
            filter_payload['filter_max_attempts'] is not None,
            filter_payload['filter_max_pct_correct'] is not None,
            filter_payload['filter_student_weighted_score_pct'] is not None,
            filter_payload['filter_student_attempts'] is not None,
        ])

        score = 0
        results = []
        total_marks = 0
        attempted_question_count = 0

        # Only score questions that have at least one selected answer.
        submitted_answers = {
            str(question_id): [int(answer_id) for answer_id in (selected_ids or []) if answer_id]
            for question_id, selected_ids in (answers or {}).items()
            if selected_ids
        }
        submitted_ids = {int(question_id) for question_id in submitted_answers}
        effective_questions = quiz.question_ids
        questions_to_score = effective_questions.filtered(lambda q: q.id in submitted_ids) if submitted_ids else effective_questions.browse([])

        for question in questions_to_score:
            q_id = str(question.id)
            selected_ids = set(submitted_answers.get(q_id) or [])
            correct_ids = set(question.answer_ids.filtered('is_correct').ids)

            if selected_ids:
                attempted_question_count += 1

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

        if questions_to_score and not has_active_filters and attempted_question_count < len(questions_to_score):
            total_marks = max(10, attempted_question_count)

        # Persist one quiz.response record for every answer the student selected
        response_vals = []
        attempt_tokens = {result['question_id']: uuid.uuid4().hex for result in results}
        for r in results:
            for a in r['answers']:
                if a['was_selected']:
                    response_vals.append({
                        'quiz_id': quiz.id,
                        'question_id': r['question_id'],
                        'answer_id': a['id'],
                        'user_id': self.env.user.id,
                        'attempt_token': attempt_tokens[r['question_id']],
                        'is_correct': a['is_correct'],
                    })
        if response_vals:
            self.env['quiz.response'].sudo().create(response_vals)

        # Recompute stored stats on affected questions and their answers.
        # Use sudo() because students do not have write access to quiz.question
        # or quiz.answer (the stats fields are teacher-facing read-only counters).
        affected_q_ids = [r['question_id'] for r in results]
        self.env['quiz.question'].sudo()._recompute_stats(affected_q_ids)

        student_stats = self._get_student_question_attempt_stats(effective_questions, self.env.user)
        student_question_stats = {
            str(question.id): {
                'attempt_count': stats['attempt_count'],
                'weighted_score_pct': round(stats['weighted_score_pct'] or 0),
                'last_answered_at': stats['last_answered_at'],
            }
            for question, stats in ((question, student_stats.get(question.id, {'attempt_count': 0, 'weighted_score_pct': None, 'last_answered_at': None})) for question in effective_questions)
        }
        student_progress_summary = self._build_student_progress_summary(quiz, filter_payload, student_stats)

        # â”€â”€ Per-question response stats for teacher users â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        return {
            'score': score,
            'total_marks': total_marks,
            'results': results,
            'is_teacher': is_teacher,
            'student_question_stats': student_question_stats,
            'student_progress_summary': student_progress_summary,
        }




# -*- coding: utf-8 -*-
"""Quiz Race live game engine.

Students race through the same set of multiple-choice questions at their own
pace.  Each correct answer moves their avatar further around the screen
perimeter; wrong answers cost time but no distance.  First to answer all
questions (or highest position when the host ends the race) wins.
"""

import random

from odoo import _, exceptions, fields

from .live_game_engine import LiveGameEngine, register_engine

# Scoring defaults (overridable per session via ``config``).
DEFAULT_POINTS_PER_CORRECT = 100
DEFAULT_SPEED_BONUS_MAX = 50  # extra points for fast answers


@register_engine('quiz_race', 'Quiz Race')
class QuizRaceEngine(LiveGameEngine):
    """Self-paced MCQ race over a quiz.quiz question set."""

    # ------------------------------------------------------------------
    # Question ordering
    # ------------------------------------------------------------------
    def _get_question_ids(self, session):
        """Ordered question ids for this session.

        With ``config.shuffle_questions`` a deterministic per-session order is
        generated once and stored in ``config.question_order`` so every client
        agrees on the sequence.
        """
        config = dict(session.config or {})
        order = config.get('question_order')
        if order:
            return [qid for qid in order if qid in set(session.quiz_id.question_ids.ids)]

        questions = session.quiz_id._filtered_questions()
        question_ids = questions.ids
        if config.get('shuffle_questions'):
            rng = random.Random(f"live-game-{session.id}")
            rng.shuffle(question_ids)
        config['question_order'] = question_ids
        session.write({'config': config})
        return question_ids

    def _participant_index(self, participant):
        progress = participant.progress or {}
        try:
            index = int(progress.get('question_index', 0))
        except (TypeError, ValueError):
            index = 0
        return max(0, index)

    def _is_finished(self, participant, total):
        return self._participant_index(participant) >= total > 0

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    def on_session_start(self, session):
        # Freeze the question order at start so late config edits cannot
        # change the race mid-flight.
        self._get_question_ids(session)

    def build_public_state(self, session):
        return {
            'question_count': len(session.quiz_id.question_ids) if session.quiz_id else 0,
        }

    def build_snapshot(self, session, participant=None):
        snapshot = {}
        if session.state == 'running' and participant:
            question = self.get_question(session, participant)
            if question:
                snapshot['question'] = question
        return snapshot

    # ------------------------------------------------------------------
    # Gameplay RPCs
    # ------------------------------------------------------------------
    def handle_rpc(self, session, participant, method, params):
        """Handle a game-specific RPC from a participant."""
        params = params or {}
        if method == 'get_question':
            return {'question': self.get_question(session, participant)}
        if method == 'submit_answer':
            return self.submit_answer(session, participant, params)
        return super().handle_rpc(session, participant, method, params)

    def get_question(self, session, participant):
        """Sanitized current question for one participant.

        Mirrors ``quiz.quiz.get_quiz_for_student``: answers are shuffled and
        correctness flags are stripped server-side so clients cannot cheat.
        """
        question_ids = self._get_question_ids(session)
        total = len(question_ids)
        index = self._participant_index(participant)

        if not total:
            return None
        if index >= total:
            return None

        question = session.env['quiz.question'].sudo().browse(question_ids[index])
        answers = list(question.answer_ids)
        random.shuffle(answers)
        return {
            'index': index,
            'total': total,
            'id': question.id,
            'question_text': question.question_text or '',
            'marks': question.marks,
            'allow_multiple': question.allow_multiple,
            'answers': [
                {'id': answer.id, 'answer_text': answer.answer_text or ''}
                for answer in answers
            ],
            'asked_at': fields.Datetime.now(),
        }

    def submit_answer(self, session, participant, params):
        """Validate an answer, score it, advance the participant.

        Idempotent: answering the same question twice keeps the first result.
        """
        question_ids = self._get_question_ids(session)
        total = len(question_ids)
        index = self._participant_index(participant)

        if session.state != 'running':
            raise exceptions.UserError(_("The race is not running."))
        if not total or index >= total:
            return {'finished': True}

        try:
            selected_ids = {int(aid) for aid in (params.get('answer_ids') or [])}
        except (TypeError, ValueError):
            raise exceptions.UserError(_("Invalid answer selection.")) from None

        progress = dict(participant.progress or {})
        answered = progress.setdefault('answered', {})
        key = str(question_ids[index])
        if key in answered:
            # Replay / double click — return the original verdict.
            previous = answered[key]
            return {
                'correct': previous.get('correct', False),
                'correct_answer_ids': [],
                'next_index': index + 1,
                'total': total,
                'finished': index + 1 >= total,
                'score': participant.score,
                'position': participant.position,
            }

        question = session.env['quiz.question'].sudo().browse(question_ids[index])
        correct_ids = set(question.answer_ids.filtered('is_correct').ids)
        correct = bool(selected_ids) and selected_ids == correct_ids

        config = session.config or {}
        points_per_correct = int(config.get('points_per_correct', DEFAULT_POINTS_PER_CORRECT))
        speed_bonus_max = int(config.get('speed_bonus_max', DEFAULT_SPEED_BONUS_MAX))

        earned = 0
        if correct:
            earned = points_per_correct
            if speed_bonus_max:
                asked_at = params.get('asked_at')
                elapsed = None
                if isinstance(asked_at, str) and asked_at:
                    try:
                        asked_dt = fields.Datetime.to_datetime(asked_at)
                        elapsed = max(0.0, (fields.Datetime.now() - asked_dt).total_seconds())
                    except ValueError:
                        elapsed = None
                if elapsed is None:
                    elapsed = float(params.get('elapsed_seconds') or 0.0)
                # Full bonus under 5 s, linearly decaying to zero at 30 s.
                ratio = max(0.0, min(1.0, (30.0 - min(elapsed, 30.0)) / 25.0))
                earned += round(speed_bonus_max * ratio)
        elif not selected_ids:
            raise exceptions.UserError(_("No answer selected."))

        answered[key] = {'correct': correct, 'earned': earned}
        next_index = index + 1
        progress['question_index'] = next_index
        progress['correct_count'] = sum(1 for a in answered.values() if a.get('correct'))

        new_score = participant.score + earned
        new_position = round(100.0 * next_index / total, 2) if total else 100.0
        finished = next_index >= total

        participant._update_progress(
            score=new_score,
            position=new_position,
            state='finished' if finished else 'playing',
            progress=progress,
        )

        return {
            'correct': correct,
            'correct_answer_ids': sorted(correct_ids),
            'points_earned': earned,
            'next_index': next_index,
            'total': total,
            'finished': finished,
            'score': new_score,
            'position': new_position,
        }

/** @odoo-module **/
import { Component, useState, onWillStart, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    APS_SUBMISSION_MODEL,
    saveToApsSubmission,
    createSubmissionCopy,
} from "@educational_games/js/utils/aps_submission";

export class QuizGame extends Component {
    static template = "quiz_game.QuizTemplate";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        const context = this.props.action.context || {};
        const actionParams = this.props.action.params || {};
        const urlParams = this._getUrlQueryParams();
        const storageKey = this._getLaunchStorageKey();
        const storedParams = this._loadStoredLaunchParams(storageKey);

        // Context lookup precedence:
        // 1) action.context (runtime launch), 2) action.params (router),
        // 3) URL query string (direct URL), 4) sessionStorage (hard-refresh fallback).
        const getParam = (key) => {
            for (const source of [context, actionParams, urlParams, storedParams]) {
                if (!source) {
                    continue;
                }
                const value = source[key];
                if (value !== undefined && value !== null && value !== "") {
                    return value;
                }
            }
            return undefined;
        };

        this.orm = useService("orm");
        this.notification = useService("notification");

        const arStr = getParam("allowResubmission");
        // Read submission_state early so we can initialise retakeMode correctly below.
        const initialSubmissionState = getParam("submission_state");
        const allowResubmission = this._toBool(arStr);
        const routeResId = this._extractRecordIdFromActionRoute();

        this.state = useState({
            loading: true,
            quiz: null,
            submitted: false,
            isCheckingAll: false,
            score: 0,
            totalMarks: 0,
            results: [],
            submission_submitted: false,
            activeQuestionId: null,
            isTeacher: false,
            // retakeMode becomes true after resetQuiz so onGameFinished can
            // distinguish a first submission from a subsequent retake.
            // It also starts as true when the existing submission record is
            // already submitted and allowResubmission is enabled — so the first
            // submit in this session creates a new copy rather than showing the
            // "already submitted" error toast.
            retakeMode: allowResubmission && !!initialSubmissionState && initialSubmissionState !== "assigned",
            // allowResubmission is True (Python bool) when set by action_preview_quiz,
            // or 'true' (string) when passed via a URL parameter.
            allowResubmission: allowResubmission,
            // Font size multiplier for question and answer text (em units).
            // Range: 0.7 – 1.5, step 0.1.
            fontSizeEm: 1.0,
            // Toggle between playing-card style and classic radio/checkbox style.
            useCards: true,
            // When true each question gets a different random card-back;
            // when false all questions share the same card-back image.
            randomCardBacks: true,
        });

        this.resId = this._toInt(getParam("active_id")) || routeResId;
        this.resModel = getParam("active_model");
        this.quizId = this._toInt(getParam("quiz_id"));
        this.quizToken = getParam("quiz_token");
        // Legacy plain params are still read for backward compatibility, but
        // signed quiz_token is preferred and enforced server-side.
        this.questionCount = this._toInt(getParam("questionCount")) || 0;
        this.optionCount = this._toInt(getParam("optionCount")) || 0;
        this.submissionModel = APS_SUBMISSION_MODEL;
        this.isValidSubmission = (this.resModel === APS_SUBMISSION_MODEL && !!this.resId);
        this.submission_state = initialSubmissionState;

        // Track the current target submission ID; may change on each resubmission
        // so that every retake (when allowResubmission=true) writes to a new record.
        this.currentSubmissionId = this.resId;

        // Persist launch parameters for hard refresh and also mirror them into
        // URL/state so this screen can be opened from a normal URL.
        this._persistLaunchParams(storageKey, {
            quiz_id: this.quizId,
            quiz_token: this.quizToken,
            active_id: this.resId,
            active_model: this.resModel,
            submission_state: this.submission_state,
        });
        this._syncActionRouteState({
            quiz_id: this.quizId,
            quiz_token: this.quizToken,
            active_id: this.resId,
            active_model: this.resModel,
            submission_state: this.submission_state,
        });

        onWillStart(async () => {
            // Load persisted display preferences (font size, card mode).
            try {
                const prefs = await this.orm.call("quiz.preference", "get_preferences", []);
                if (prefs) {
                    this.state.fontSizeEm = prefs.font_size_em ?? 1.0;
                    this.state.useCards = prefs.use_cards ?? true;
                }
            } catch (_e) {
                // Preference table may not exist yet; keep defaults.
            }

            // Last-ditch fallback: in direct `/odoo/action-.../<id>/...` URLs,
            // use that record id as quiz_id if no explicit quiz_id is present.
            if (!this.quizId && routeResId) {
                this.quizId = routeResId;
            }
            if (this.quizId) {
                await this.loadQuiz();
            } else {
                this.state.loading = false;
            }
        });
    }

    async loadQuiz() {
        try {
            const quizData = await this.orm.call(
                "quiz.quiz",
                "get_quiz_for_student",
                [this.quizId],
                {
                    quiz_token: this.quizToken,
                    question_count: this.questionCount,
                    option_count: this.optionCount,
                }
            );
            // Add reactive selected-answer tracking to each question
            const sharedCardBack = this._randomCardBackUrl();
            quizData.questions.forEach((q) => {
                q.selected_answers = [];
                q.result = null; // populated after submission or individual check
                q.checked = false; // true when teacher has revealed this question's answer
                q.responseStats = {}; // per-answer-id response statistics
                q.showDual = false;    // true when stats have both old + recent data
                q.totalRespondents = 0;
                q.recentRespondents = 0;
                // Assign card-back image: random per question or shared across all.
                q.cardBackUrl = this.state.randomCardBacks
                    ? this._randomCardBackUrl()
                    : sharedCardBack;
                // Mark HTML strings as safe for t-out rendering
                q.question_text = markup(q.question_text || "");
                q.answers.forEach((a) => {
                    a.answer_text = markup(a.answer_text || "");
                });
            });
            this.state.quiz = quizData;
            this.state.totalMarks = quizData.total_marks;
            this.state.isTeacher = quizData.is_teacher || false;
            if (typeof quizData.allow_resubmission === "boolean") {
                this.state.allowResubmission = quizData.allow_resubmission;
            }
            // Token-based allow_resubmission arrives from the server after setup().
            // Re-evaluate initial retake mode now so existing submitted tasks can
            // immediately enter resubmission flow when enabled by token.
            if (
                !this.state.retakeMode &&
                this.isValidSubmission &&
                this.submission_state &&
                this.submission_state !== "assigned" &&
                this.state.allowResubmission
            ) {
                this.state.retakeMode = true;
            }
            // Activate first question by default
            if (quizData.questions.length > 0) {
                this.state.activeQuestionId = quizData.questions[0].id;
            }
        } catch (error) {
            console.error("Error loading quiz:", error);
            this.notification.add("Error loading quiz. Please try again.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    /** Returns the letter label (A, B, C, …) for the nth answer option. */
    getAnswerLetter(index) {
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[index] || String(index + 1);
    }

    /** Pick a random card-back image URL from the pool. */
    _randomCardBackUrl() {
        const images = [
            "/educational_games/static/src/img/card_backs/card_feather.jpg",
            "/educational_games/static/src/img/card_backs/card_rainbow.jpg",
            "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExMm5wOW04ZGJ6ZnR2azJpY2QzOHdzNmJ1bTFwcTU3NzU1M3liZDJ6ZiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/aMMWn9Ogf3UOI/giphy.gif",
            "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaXhzZ2FwcHNwZmticDU3amwwa2t1NWJmbjJqdndoZ3oycDY1NDZrZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/BqK5K4OD1X3RdlfJxH/giphy.gif",
            "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExdGJxd2R3YnJ3YWx4OGl6M2o2aWp5bzcwZThrdGh5bDg5OHY0cnl5MyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/cYZkY9HeKgofpQnOUl/giphy.gif", /** Chiuaha Dog**/
            "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExdzZqeWllN2JyM29jcG91bXRoNGltcmxmb25iMTBkd2djeXZ6d2hrNyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/rZ7A5ayCa2zVcMgsvl/giphy.gif", /** Cat kick duckling **/
            "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExZGpsbnR4MzZzanY5NTcwbDdpYTliNTRvcm9sdjgxYjhzemN2dThjeiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/jkTTVVRZGbQ1fBIFOX/giphy.gif", /** Happy dinosuars **/
            "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDJsbmJqYzN2eHk3OXhhYjk1cGlwdHEycWl3eDEzZGI3ZWFtbTBwbSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/H986cBWlQH0PXjcLQO/giphy.gif", /** Baby Yoda **/
            "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExYWN5cGVvOXlzZXFncGJxazVsNzR0eW9zZW01dndydXJ4dGw1ZG00NyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Oi6tJtKNThC6I/giphy.gif", /** Frozen Yippie **/
            "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExam1jejl4a3dpM2xtbnYzMjY3ZXBzMnh4dm13OGlyc3RscDRvaGdsdCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/EvYHHSntaIl5m/giphy.gif", /** Monster Hug **/
            "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExdmsyMngxb2FmcHczdHE1dWJxNjZ5eHJ0cGh2c2gxcDJlYXU3OG92OSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/sC2mGly8IxF2E/giphy.gif", /** Disney Dog Kiss **/
            "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExc2dwajM0Ynlrbzk2YjNzbGZiYWc1MGwzeHQ4MTcyMDZzc2lzM3F0dCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/jAX4NpDPfcmUHwTNAf/giphy.gif", /** Motocross jump **/
            "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExY2N3cG02dzE5aHN2ZXNqZnF0eGJ3enhndW4ydjlsZXYyeWF6ZXdpYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/RhSsbdJGG0ZvCMoTIl/giphy.gif", /** Motocross Backflip **/
            "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExd2IzYTU2dm5ycHZ6bXN0OXJtaW1zN2wwZ2M4cnUwNTE1dml6eWlkZyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/BNR91YsnOC9I59011H/giphy.gif", /** Send it **/
            "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExeTF0cDF2MW5wdWp1cmQyN2t2YXIxd2doNXVxdG9uamF2MG16dXVveSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/1xkMJIvxeKiDS/giphy.gif", /** The Flash **/  
            "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExZm1iYm1nZHpvNXJ1YnRtazVpMXBzaDgzbWU4ZHBxbzBpMXMzazlhMiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/14b13BDH3V81wc/giphy.gif", /** Baby groot **/
            "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExcG5uajZjYWVpc2R5NG0wZmpyaGJ3YWlhbWdhOG91bmNsYzNlcW04cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ckAsLajQY6HxYHYRDX/giphy.gif", /** Surf **/
            
        ];
        return images[Math.floor(Math.random() * images.length)];
    }

    /**
     * Returns the TOC/card status for a question.
     * @returns {'unanswered'|'answered'|'correct'|'incorrect'}
     */
    getQuestionStatus(question) {
        if ((this.state.submitted || question.checked) && question.result) {
            return question.result.is_correct ? "correct" : "incorrect";
        }
        return question.selected_answers.length > 0 ? "answered" : "unanswered";
    }

    /** Set the currently highlighted question. */
    setActiveQuestion(questionId) {
        this.state.activeQuestionId = questionId;
    }

    /** Scroll to a question card and activate it. */
    scrollToQuestion(questionId) {
        this.state.activeQuestionId = questionId;
        const el = document.querySelector(`[data-question-id="${questionId}"]`);
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    /** Switch between card and classic radio/checkbox answer display. */
    toggleCardMode() {
        this.state.useCards = !this.state.useCards;
        this._savePreferences();
    }

    /** Increase the question/answer font size by one step (max 1.5em). */
    increaseFontSize() {
        const maxFontSize = 7;
        if (this.state.fontSizeEm < maxFontSize) {
            this.state.fontSizeEm = Math.min(maxFontSize, Math.round((this.state.fontSizeEm + 0.2) * 10) / 10);
            this._savePreferences();
        }
    }

    /** Decrease the question/answer font size by one step (min 0.7em). */
    decreaseFontSize() {
        const minFontSize = 0.3;
        if (this.state.fontSizeEm > minFontSize) {
            this.state.fontSizeEm = Math.max(minFontSize, Math.round((this.state.fontSizeEm - 0.2) * 10) / 10);
            this._savePreferences();
        }
    }

    /** Persist current display preferences to the database (fire-and-forget). */
    _savePreferences() {
        this.orm.call("quiz.preference", "set_preferences", [], {
            use_cards: this.state.useCards,
            font_size_em: this.state.fontSizeEm,
        }).catch(() => {});
    }

    /**
     * Toggle an answer selection for a given question.
     * Single-answer questions: replaces any previous selection (radio behavior).
     * Multiple-answer questions: toggles the answer on/off (checkbox behavior).
     */
    toggleAnswer(question, answer) {
        if (this.state.submitted || question.checked) return;
        this.state.activeQuestionId = question.id;
        if (question.allow_multiple) {
            const idx = question.selected_answers.indexOf(answer.id);
            if (idx === -1) {
                question.selected_answers.push(answer.id);
            } else {
                question.selected_answers.splice(idx, 1);
            }
        } else {
            // Single-answer: replace selection
            question.selected_answers.splice(0, question.selected_answers.length, answer.id);
        }
    }

    async submitQuiz() {
        if (this.state.submitted) return;

        if (this.state.isTeacher) {
            const confirmed = window.confirm("Do you really want to save your responses?");
            if (!confirmed) {
                return;
            }
        }

        // Build payload: { "questionId": [answerId, ...] }
        const answers = {};
        for (const question of this.state.quiz.questions) {
            answers[String(question.id)] = question.selected_answers;
        }

        try {
            const result = await this.orm.call("quiz.quiz", "submit_quiz_answers", [this.quizId, answers]);

            // Merge server results back into quiz state for display
            result.results.forEach((r) => {
                const question = this.state.quiz.questions.find((q) => q.id === r.question_id);
                if (question) {
                    question.result = r;
                    // Populate response stats when the server returns them (teacher submit)
                    if (r.response_stats !== undefined) {
                        question.responseStats = r.response_stats;
                        question.showDual = r.show_dual || false;
                        question.totalRespondents = r.total_respondents || 0;
                        question.recentRespondents = r.recent_respondents || 0;
                        question.checked = true;
                    }
                }
            });

            this.state.score = result.score;
            this.state.totalMarks = result.total_marks;
            this.state.results = result.results;
            this.state.submitted = true;
            this.state.activeQuestionId = null;

            await this.onGameFinished(result.score, result.results);
        } catch (error) {
            console.error("Error submitting quiz:", error);
            this.notification.add("Error submitting quiz. Please try again.", { type: "danger" });
        }
    }

    /**
     * Teacher-only: reveal the correct answer(s) for a single question without
     * submitting the whole quiz.  Populates question.result and sets
     * question.checked = true so the template shows result styling for that
     * question only.
     */
    async checkAnswer(question) {
        if (this.state.submitted || question.checked) return;

        try {
            await this._revealQuestionAnswer(question);
        } catch (error) {
            console.error("Error checking answer:", error);
            this.notification.add("Error checking answer. Please try again.", { type: "danger" });
        }
    }

    async checkAllAnswers() {
        if (this.state.submitted || !this.state.isTeacher || this.state.isCheckingAll) return;

        const toCheck = this.state.quiz.questions.filter((question) => !question.checked);
        if (!toCheck.length) {
            return;
        }

        this.state.isCheckingAll = true;
        try {
            const checkResults = await Promise.allSettled(
                toCheck.map((question) => this._revealQuestionAnswer(question))
            );
            const failed = checkResults.filter((entry) => entry.status === "rejected").length;

            if (failed) {
                this.notification.add(
                    `Checked ${toCheck.length - failed} question(s). ${failed} failed.`,
                    { type: "warning" }
                );
            } else {
                this.notification.add(
                    "Correct answers revealed. Responses have not been saved.",
                    { type: "info" }
                );
            }
        } catch (error) {
            console.error("Error checking all answers:", error);
            this.notification.add("Error checking answers. Please try again.", { type: "danger" });
        } finally {
            this.state.isCheckingAll = false;
        }
    }

    async _revealQuestionAnswer(question) {
        const data = await this.orm.call(
            "quiz.quiz",
            "check_single_question",
            [this.quizId, question.id]
        );
        const selectedIds = question.selected_answers;
        const correctIds = data.correct_answer_ids;
        const isCorrect =
            correctIds.length > 0 &&
            selectedIds.length === correctIds.length &&
            selectedIds.every((id) => correctIds.includes(id));

        question.result = {
            question_id: question.id,
            question_text: data.question_text,
            is_correct: isCorrect,
            correct_answer_ids: correctIds,
            selected_answer_ids: selectedIds,
            marks: data.marks,
            answers: data.answers.map((a) => ({
                id: a.id,
                answer_text: a.answer_text,
                is_correct: a.is_correct,
                was_selected: selectedIds.includes(a.id),
            })),
        };
        question.responseStats = data.response_stats || {};
        question.showDual = data.show_dual || false;
        question.totalRespondents = data.total_respondents || 0;
        question.recentRespondents = data.recent_respondents || 0;
        question.checked = true;
    }

    _stripHtml(html) {
        if (!html) return "";
        // Use DOM to safely extract text content (avoids incomplete regex sanitization)
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "";
    }

    _escapeHtml(text) {
        const div = document.createElement("div");
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    /**
     * Build a plain-text HTML report for storing in the submission's answer field.
     *
     * Each question is shown as a row with:
     *   ✅ / ❌  question text (plain, no HTML formatting)  (N mark/marks)
     *
     * The report intentionally avoids images and rich formatting so it is
     * readable in the APEX submission viewer.
     */
    _buildAnswerHtml(results, score, totalMarks) {
        const safeText = (html) => this._escapeHtml(this._stripHtml(html));
        const rows = results.map((r) => {
            const icon = r.is_correct ? "✅" : "❌";
            const marksLabel = r.marks === 1 ? "1 mark" : `${r.marks} marks`;
            return `<tr>
                <td style="padding:6px 10px;border:1px solid #dee2e6;font-size:1.1em;width:36px;">${icon}</td>
                <td style="padding:6px 10px;border:1px solid #dee2e6;">${safeText(r.question_text)} <em style="color:#6c757d;">(${marksLabel})</em></td>
            </tr>`;
        }).join("");

        return `<p style="font-family:sans-serif;"><strong>Score: ${score} / ${totalMarks}</strong></p>
            <table style="width:100%;border-collapse:collapse;margin-top:8px;font-family:sans-serif;font-size:0.95em;">
                <tbody>${rows}</tbody>
            </table>`;
    }

    /**
     * Called when the student submits the quiz.
     *
     * Saves the result to the linked aps.resource.submission when one exists,
     * using the shared saveToApsSubmission() utility from aps_submission.js.
     *
     * Resubmission flow (allowResubmission=true):
     *   - First submission:  writes to the original submission record.
     *   - Retake:            creates a new submission copy (no due date) via
     *                        createSubmissionCopy(), then writes to it.
     *
     * Practice flow (allowResubmission=false or no submission context):
     *   - Retake:            shows a practice-score toast; nothing is saved.
     */
    async onGameFinished(finalScore, results) {
        const htmlReport = this._buildAnswerHtml(results, finalScore, this.state.totalMarks);

        // No submission context — always show practice score toast
        if (!this.isValidSubmission) {
            this.notification.add(
                `Practice Score: ${finalScore} / ${this.state.totalMarks}`,
                { type: "info" }
            );
            return;
        }

        // Retake after a previous submission
        if (this.state.retakeMode) {
            if (this.state.allowResubmission) {
                // Create a new submission copy and save to it
                const newId = await createSubmissionCopy(this.orm, this.notification, this.currentSubmissionId);
                if (newId) {
                    const saved = await saveToApsSubmission(this.orm, this.notification, newId, finalScore, htmlReport, this.state.totalMarks);
                    if (saved) {
                        this.currentSubmissionId = newId;
                        this.state.submission_submitted = true;
                    }
                }
            } else {
                // Practice retake — do not save
                this.notification.add(
                    `Practice Score: ${finalScore} / ${this.state.totalMarks}. Results not saved.`,
                    { type: "info" }
                );
            }
            return;
        }

        // First submission: check that it hasn't already been submitted
        if (this.submission_state !== "assigned") {
            this.notification.add(
                "This task has already been submitted so these results cannot be saved.",
                { type: "info" }
            );
            return;
        }

        const saved = await saveToApsSubmission(
            this.orm, this.notification, this.currentSubmissionId, finalScore, htmlReport, this.state.totalMarks
        );
        if (saved) {
            this.state.submission_submitted = true;
            this.submission_state = "submitted";
        }
    }

    resetQuiz() {
        // Mark subsequent submissions as retakes so onGameFinished handles them correctly
        this.state.retakeMode = true;
        this.state.submitted = false;
        this.state.isCheckingAll = false;
        this.state.score = 0;
        this.state.results = [];
        this.state.submission_submitted = false;
        this.state.activeQuestionId = null;
        this.state.loading = true;
        this.loadQuiz();
    }

    _toInt(value) {
        const asInt = parseInt(value, 10);
        return Number.isFinite(asInt) ? asInt : null;
    }

    _toBool(value) {
        return value === true || value === 1 || value === "1" || value === "true";
    }

    _getUrlQueryParams() {
        const out = {};
        const search = window.location?.search || "";
        const params = new URLSearchParams(search);
        for (const [key, value] of params.entries()) {
            out[key] = value;
        }
        return out;
    }

    _getLaunchStorageKey() {
        return `educational_games.quiz.launch:${window.location.pathname}`;
    }

    _loadStoredLaunchParams(storageKey) {
        try {
            const raw = window.sessionStorage.getItem(storageKey);
            if (!raw) {
                return {};
            }
            return JSON.parse(raw) || {};
        } catch {
            return {};
        }
    }

    _persistLaunchParams(storageKey, payload) {
        if (!payload.quiz_id) {
            return;
        }

        try {
            window.sessionStorage.setItem(storageKey, JSON.stringify(payload));
        } catch {
            // Ignore storage failures (private mode/quota).
        }

        // Ensure launch params are visible in the URL so hard refresh/direct
        // navigation has enough context even without prior session storage.
        try {
            const url = new URL(window.location.href);
            const keys = [
                "quiz_id",
                "quiz_token",
                "active_id",
                "active_model",
                "submission_state",
            ];
            const concealKeys = ["questionCount", "optionCount", "allowResubmission"];
            let changed = false;

            for (const key of keys) {
                const value = payload[key];
                if (value === undefined || value === null || value === "" || value === false) {
                    continue;
                }
                const strValue = String(value);
                if (url.searchParams.get(key) !== strValue) {
                    url.searchParams.set(key, strValue);
                    changed = true;
                }
            }

            // Remove raw tuning params so difficulty is not user-editable.
            for (const key of concealKeys) {
                if (url.searchParams.has(key)) {
                    url.searchParams.delete(key);
                    changed = true;
                }
            }

            if (changed) {
                window.history.replaceState(window.history.state, "", url.toString());
            }
        } catch {
            // Ignore URL manipulation errors.
        }
    }

    _syncActionRouteState(payload) {
        if (!this.props.updateActionState || !payload.quiz_id) {
            return;
        }
        this.props.updateActionState(payload);
    }

    _extractRecordIdFromActionRoute() {
        const path = window.location?.pathname || "";
        // Typical path: /odoo/action-1136/1/action_quiz_game_js
        const match = path.match(/\/odoo\/action-[^/]+\/(\d+)(?:\/|$)/);
        if (!match) {
            return null;
        }
        return this._toInt(match[1]);
    }
}

registry.category("actions").add("action_quiz_game_js", QuizGame);


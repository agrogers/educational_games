/** @odoo-module **/
import { Component, useState, onWillStart, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

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

        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            quiz: null,
            submitted: false,
            score: 0,
            totalMarks: 0,
            results: [],
            submission_submitted: false,
            activeQuestionId: null,
        });

        this.resId = context.active_id;
        this.resModel = context.active_model;
        this.quizId = context.quiz_id;
        this.submissionModel = "aps.resource.submission";
        this.isValidSubmission = (this.resModel === this.submissionModel && !!this.resId);
        this.submission_state = context.submission_state;

        onWillStart(async () => {
            if (this.quizId) {
                await this.loadQuiz();
            } else {
                this.state.loading = false;
            }
        });
    }

    async loadQuiz() {
        try {
            const quizData = await this.orm.call("quiz.quiz", "get_quiz_for_student", [this.quizId]);
            // Add reactive selected-answer tracking to each question
            quizData.questions.forEach((q) => {
                q.selected_answers = [];
                q.result = null; // populated after submission
                // Mark HTML strings as safe for t-out rendering
                q.question_text = markup(q.question_text || "");
                q.answers.forEach((a) => {
                    a.answer_text = markup(a.answer_text || "");
                });
            });
            this.state.quiz = quizData;
            this.state.totalMarks = quizData.total_marks;
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

    /**
     * Returns the TOC/card status for a question.
     * @returns {'unanswered'|'answered'|'correct'|'incorrect'}
     */
    getQuestionStatus(question) {
        if (this.state.submitted && question.result) {
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

    /**
     * Toggle an answer selection for a given question.
     * Single-answer questions: replaces any previous selection (radio behavior).
     * Multiple-answer questions: toggles the answer on/off (checkbox behavior).
     */
    toggleAnswer(question, answer) {
        if (this.state.submitted) return;
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

    _buildAnswerHtml(results) {
        const safeText = (html) => this._escapeHtml(this._stripHtml(html));
        const rows = results
            .map((r) => {
                const bgColor = r.is_correct ? "#d4edda" : "#f8d7da";
                const textColor = r.is_correct ? "#155724" : "#721c24";
                const status = r.is_correct ? "✓ Correct" : "✗ Incorrect";

                const correctAnswers = r.answers
                    .filter((a) => a.is_correct)
                    .map((a) => safeText(a.answer_text))
                    .join(", ");

                const selectedAnswers =
                    r.answers
                        .filter((a) => a.was_selected)
                        .map((a) => safeText(a.answer_text))
                        .join(", ") || "(None selected)";

                return `
                    <tr>
                        <td style="padding:8px;border:1px solid #dee2e6;">${safeText(r.question_text)}</td>
                        <td style="padding:8px;border:1px solid #dee2e6;background:${bgColor};color:${textColor};">${selectedAnswers}</td>
                        <td style="padding:8px;border:1px solid #dee2e6;">${correctAnswers}</td>
                        <td style="padding:8px;border:1px solid #dee2e6;background:${bgColor};color:${textColor};font-weight:bold;">${status}</td>
                    </tr>`;
            })
            .join("");

        return `
            <table style="width:100%;border-collapse:collapse;margin-top:10px;font-family:sans-serif;">
                <thead>
                    <tr style="background:#f8f9fa;">
                        <th style="padding:8px;border:1px solid #dee2e6;text-align:left;">Question</th>
                        <th style="padding:8px;border:1px solid #dee2e6;text-align:left;">Your Answer(s)</th>
                        <th style="padding:8px;border:1px solid #dee2e6;text-align:left;">Correct Answer(s)</th>
                        <th style="padding:8px;border:1px solid #dee2e6;text-align:left;">Result</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    async onGameFinished(finalScore, results) {
        if (!this.isValidSubmission) {
            this.notification.add(
                `Practice Score: ${finalScore} / ${this.state.totalMarks}`,
                { type: "info" }
            );
            return;
        }

        if (this.submission_state !== "assigned") {
            this.notification.add(
                "This task has already been submitted so these results cannot be saved.",
                { type: "info" }
            );
            return;
        }

        const htmlReport = this._buildAnswerHtml(results);

        try {
            await this.orm.write(this.submissionModel, [this.resId], {
                score: finalScore,
                answer: htmlReport,
                state: "submitted",
            });
            this.notification.add("Results saved successfully!", { type: "success" });
            this.state.submission_submitted = true;
        } catch (error) {
            console.error("Error saving submission:", error);
            this.notification.add("Error saving results. Please contact your teacher.", { type: "danger" });
        }
    }

    resetQuiz() {
        this.state.submitted = false;
        this.state.score = 0;
        this.state.results = [];
        this.state.submission_submitted = false;
        this.state.activeQuestionId = null;
        this.state.loading = true;
        this.loadQuiz();
    }
}

registry.category("actions").add("action_quiz_game_js", QuizGame);


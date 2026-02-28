/** @odoo-module **/
import { Component, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BinaryAdderGame extends Component {
    static template = "binaryadder2.GameTemplate";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        const context = this.props.action.context || {};
        debugger;
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loading: false,
            checked: false,
            started: false,
            score: 0,
            questions: [],
            submission_state: context.submission_state,
            submission_submitted: false,
            format: context.format || "binary",
            num_count: parseInt(context.num_count, 10) || 2,
            level: context.level || "easy",
            num_questions: parseInt(context.out_of_marks, 10) || 10,
            timer_seconds: 0,
        });

        this.resId = context.active_id;
        this.resModel = context.active_model;
        this.submissionModel = "aps.resource.submission";
        this.isValidSubmission = (this.resModel === this.submissionModel && !!this.resId);

        this.timerId = null;
        this.timerStart = null;

        onWillUnmount(() => {
            this._stopTimer();
        });

        const contextSettings = this._getContextSettings(context);
        const urlSettings = this._getUrlSettings();
        const settings = contextSettings || urlSettings;
        if (settings) {
            if (settings.format) {
                this.state.format = settings.format;
            }
            if (settings.num_count) {
                this.state.num_count = parseInt(settings.num_count, 10);
            }
            if (settings.level) {
                this.state.level = settings.level;
            }
            if (settings.num_questions) {
                this.state.num_questions = parseInt(settings.num_questions, 10);
            }
            this.startQuiz();
        }
    }

    _getContextSettings(context) {
        const format = context.format;
        const num_count = context.num_count;
        const level = context.level;
        const num_questions = context.num_questions;

        if (!format && !num_count && !level && !num_questions) {
            return null;
        }

        return {
            format,
            num_count: num_count ? parseInt(num_count, 10) : null,
            level,
            num_questions: num_questions ? parseInt(num_questions, 10) : null,
        };
    }

    _getUrlSettings() {
        const params = new URLSearchParams(window.location.search || "");
        const hash = (window.location.hash || "").replace(/^#/, "");
        const hashParams = new URLSearchParams(hash);

        const format = params.get("format") || hashParams.get("format");
        const num_count = params.get("num_count") || hashParams.get("num_count");
        const level = params.get("level") || hashParams.get("level");
        const num_questions = params.get("num_questions") || hashParams.get("num_questions");

        if (!format && !num_count && !level && !num_questions) {
            return null;
        }

        return {
            format,
            num_count: num_count ? parseInt(num_count, 10) : null,
            level,
            num_questions: num_questions ? parseInt(num_questions, 10) : null,
        };
    }

    _startTimer() {
        this._stopTimer();
        this.timerStart = Date.now();
        this.state.timer_seconds = 0;
        this.timerId = setInterval(() => {
            this.state.timer_seconds = Math.floor((Date.now() - this.timerStart) / 1000);
        }, 1000);
    }

    _stopTimer() {
        if (this.timerId) {
            clearInterval(this.timerId);
            this.timerId = null;
        }
    }

    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    _bitsForLevel(level) {
        if (level === "easy") return 4;
        if (level === "medium") return 8;
        return 12; // hard
    }

    _randInt(maxInclusive) {
        return Math.floor(Math.random() * maxInclusive) + 1;
    }

    _formatNumber(n, format, bits) {
        if (format === "binary") {
            return n.toString(2).padStart(bits, "0");
        }
        if (format === "hexadecimal") {
            return n.toString(16).toUpperCase();
        }
        return n.toString(10);
    }

    _normalizeAnswer(answer, format) {
        const raw = (answer || "").trim();
        if (!raw) {
            return null;
        }

        let cleaned = raw.toLowerCase().replace(/\s+/g, "");

        if (format === "binary") {
            cleaned = cleaned.replace(/^0b/, "");
            if (!/^[01]*$/.test(cleaned)) {
                return null;
            }
        } else if (format === "hexadecimal") {
            cleaned = cleaned.replace(/^0x/, "");
            if (!/^[0-9a-f]*$/.test(cleaned)) {
                return null;
            }
        }

        cleaned = cleaned.replace(/^0+/, "");
        if (!cleaned) {
            cleaned = "0";
        }
        return cleaned;
    }

    _generateQuestions() {
        const bits = this._bitsForLevel(this.state.level);
        const max = (1 << bits) - 1; // 2^bits - 1
        const count = parseInt(this.state.num_count, 10);
        const numQuestions = parseInt(this.state.num_questions, 10);
        const questions = [];

        for (let i = 0; i < numQuestions; i++) {
            const nums = [];
            for (let j = 0; j < count; j++) {
                nums.push(this._randInt(max));
            }

            const questionText = nums
                .map(n => this._formatNumber(n, this.state.format, bits))
                .join(" + ");
            const sum = nums.reduce((a, b) => a + b, 0);
            const correctAnswer = this._formatNumber(sum, this.state.format, bits);

            questions.push({
                uniqueId: i,
                nums,
                prompt: `${questionText} = ?`,
                correctAnswer,
                userAnswer: "",
                isCorrect: null,
            });
        }

        this.state.questions = questions;
    }

    startQuiz() {
        if (this.state.num_questions <= 0) {
            this.notification.add("Please select a valid number of questions.", { type: "warning" });
            return;
        }

        this.state.checked = false;
        this.state.submission_submitted = false;
        this.state.score = 0;
        this.state.started = true;

        this._generateQuestions();
        this._startTimer();
    }

    checkQuestion(uniqueId) {
        const question = this.state.questions.find(q => q.uniqueId === uniqueId);
        if (!question) return;

        const userNormalized = this._normalizeAnswer(question.userAnswer, this.state.format);
        const correctNormalized = this._normalizeAnswer(question.correctAnswer, this.state.format);

        if (userNormalized === null) {
            this.notification.add("Invalid format. Please check your answer.", { type: "warning" });
            return;
        }

        const isCorrect = userNormalized === correctNormalized;
        if (isCorrect && !question.isCorrect) {
            this.state.score++;
        } else if (!isCorrect && question.isCorrect) {
            this.state.score--;
        }

        question.isCorrect = isCorrect;
    }

    async checkAllAnswers() {
        this._stopTimer();

        let correctCount = 0;
        this.state.questions.forEach(q => {
            const userNormalized = this._normalizeAnswer(q.userAnswer, this.state.format);
            const correctNormalized = this._normalizeAnswer(q.correctAnswer, this.state.format);
            const isCorrect = userNormalized !== null && userNormalized === correctNormalized;

            q.isCorrect = isCorrect;
            if (isCorrect) {
                correctCount++;
            }
        });

        this.state.score = correctCount;
        this.state.checked = true;

        const gameResults = this.state.questions.map(q => ({
            prompt: q.prompt,
            userGuess: q.userAnswer || "(Empty)",
            correctAnswer: q.correctAnswer,
            isCorrect: q.isCorrect,
        }));

        await this.onGameFinished(this.state.score, gameResults);
    }

    _buildAnswerHtml(results) {
        const timeDisplay = this.formatTime(this.state.timer_seconds);
        const rows = results
            .map(res => {
                const bgColor = res.isCorrect ? "#d4edda" : "#f8d7da";
                const textColor = res.isCorrect ? "#155724" : "#721c24";

                return `
                <tr>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.prompt}</td>
                    <td style="padding: 8px; border: 1px solid #dee2e6; background-color: ${bgColor}; color: ${textColor}; font-weight: bold;">
                        ${res.userGuess}
                    </td>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.correctAnswer}</td>
                </tr>`;
            })
            .join("");

        return `
            <div style="font-family: sans-serif; margin-bottom: 8px;">
                <strong>Time taken:</strong> ${timeDisplay}
            </div>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-family: sans-serif;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Question</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Your Answer</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Correct Answer</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    async onGameFinished(finalScore, gameResults) {
        if (!this.isValidSubmission) {
            this.notification.add(
                `Practice Score: ${finalScore} out of ${this.state.questions.length} (Time: ${this.formatTime(this.state.timer_seconds)})`,
                { type: "info" }
            );
            return;
        }

        if (this.state.submission_state !== "assigned") {
            this.notification.add("This task has already been submitted so these results can not be saved.", { type: "info" });
            return;
        }

        const htmlReport = this._buildAnswerHtml(gameResults);
        const hours = Math.round((this.state.timer_seconds / 3600) * 10) / 10;

        try {
            await this.orm.write(this.submissionModel, [this.resId], {
                score: finalScore,
                answer: htmlReport,
                actual_duration: hours,
                state: "submitted",
            });
            this.notification.add("Official submission saved!", { type: "success" });
            this.state.submission_state = "submitted";
            this.state.submission_submitted = true;
        } catch (error) {
            this.notification.add("Error saving submission.", { type: "danger" });
        }
    }

    resetGame() {
        this._stopTimer();
        this.state.started = false;
        this.state.checked = false;
        this.state.questions = [];
        this.state.timer_seconds = 0;
        this.state.score = 0;
    }
}

registry.category("actions").add("action_binaryadder2_js", BinaryAdderGame);

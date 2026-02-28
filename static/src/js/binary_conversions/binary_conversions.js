/** @odoo-module **/
import { Component, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BinaryConversionsGame extends Component {
    static template = "binary_conversions.GameTemplate";
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
            loading: false,
            checked: false,
            started: false,
            score: 0,
            questions: [],
            submission_state: context.submission_state,
            submission_submitted: false,
            conversion_type: "bin_to_dec",
            number_size: context.number_size || 8,
            num_questions: context.out_of_marks || 10,
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
            if (settings.conversion_type) {
                this.state.conversion_type = settings.conversion_type;
            }
            if (settings.number_size) {
                this.state.number_size = settings.number_size;
            }
            if (settings.num_questions) {
                this.state.num_questions = settings.num_questions;
            }
            this.startQuiz();
        }
    }

    _getContextSettings(context) {
        const conversion_type = context.conversion_type;
        const number_size = context.number_size;
        const num_questions = context.num_questions;

        if (!conversion_type && !number_size && !num_questions) {
            return null;
        }

        return {
            conversion_type,
            number_size: number_size ? parseInt(number_size, 10) : null,
            num_questions: num_questions ? parseInt(num_questions, 10) : null,
        };
    }

    _getUrlSettings() {
        const params = new URLSearchParams(window.location.search || "");
        const hash = (window.location.hash || "").replace(/^#/, "");
        const hashParams = new URLSearchParams(hash);

        const conversion_type = params.get("conversion_type") || hashParams.get("conversion_type");
        const number_size = params.get("number_size") || hashParams.get("number_size");
        const num_questions = params.get("num_questions") || hashParams.get("num_questions");

        if (!conversion_type && !number_size && !num_questions) {
            return null;
        }

        return {
            conversion_type,
            number_size: number_size ? parseInt(number_size, 10) : null,
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

    _getConversionConfig(conversionType) {
        const configs = {
            bin_to_dec: { fromBase: 2, toBase: 10, fromLabel: "binary", toLabel: "decimal" },
            dec_to_bin: { fromBase: 10, toBase: 2, fromLabel: "decimal", toLabel: "binary" },
            bin_to_hex: { fromBase: 2, toBase: 16, fromLabel: "binary", toLabel: "hexadecimal" },
            hex_to_bin: { fromBase: 16, toBase: 2, fromLabel: "hexadecimal", toLabel: "binary" },
            dec_to_hex: { fromBase: 10, toBase: 16, fromLabel: "decimal", toLabel: "hexadecimal" },
            hex_to_dec: { fromBase: 16, toBase: 10, fromLabel: "hexadecimal", toLabel: "decimal" },
        };
        return configs[conversionType] || configs.bin_to_dec;
    }

    _maxValueForBase(base, size) {
        return Math.pow(base, size) - 1;
    }

    _formatValue(value, base) {
        if (base === 16) {
            return value.toString(16).toUpperCase();
        }
        return value.toString(base);
    }

    _normalizeAnswer(answer, base) {
        const raw = (answer || "").trim();
        if (!raw) {
            return null;
        }
        let cleaned = raw.toLowerCase().replace(/\s+/g, "");

        if (base === 10) {
            const num = parseInt(cleaned, 10);
            if (Number.isNaN(num)) {
                return null;
            }
            return String(num);
        }

        if (base === 2) {
            cleaned = cleaned.replace(/^0b/, "");
        }
        if (base === 16) {
            cleaned = cleaned.replace(/^0x/, "");
        }

        cleaned = cleaned.replace(/^0+/, "");
        if (!cleaned) {
            cleaned = "0";
        }
        return cleaned;
    }

    _generateQuestions() {
        const conversionType = this.state.conversion_type;
        const { fromBase, toBase, fromLabel, toLabel } = this._getConversionConfig(conversionType);

        const size = parseInt(this.state.number_size, 10);
        const count = parseInt(this.state.num_questions, 10);

        const maxValue = this._maxValueForBase(fromBase, size);
        const questions = [];

        for (let i = 0; i < count; i++) {
            const value = Math.floor(Math.random() * (maxValue + 1));
            const sourceValue = this._formatValue(value, fromBase);
            const correctAnswer = this._formatValue(value, toBase);

            questions.push({
                uniqueId: i,
                prompt: `Convert ${sourceValue} (${fromLabel}) to ${toLabel}`,
                correctAnswer,
                userAnswer: "",
                isCorrect: null,
                fromBase,
                toBase,
            });
        }

        this.state.questions = questions;
    }

    startQuiz() {
        const size = parseInt(this.state.number_size, 10);
        const count = parseInt(this.state.num_questions, 10);

        if (!size || size <= 0) {
            this.notification.add("Please enter a valid number size.", { type: "warning" });
            return;
        }
        if (!count || count <= 0) {
            this.notification.add("Please enter a valid number of questions.", { type: "warning" });
            return;
        }

        this.state.checked = false;
        this.state.submission_submitted = false;
        this.state.score = 0;
        this.state.started = true;

        this._generateQuestions();
        this._startTimer();
    }

    async checkAnswers() {
        this._stopTimer();

        let correctCount = 0;
        this.state.questions.forEach(q => {
            const userNormalized = this._normalizeAnswer(q.userAnswer, q.toBase);
            const correctNormalized = this._normalizeAnswer(q.correctAnswer, q.toBase);
            const isCorrect = userNormalized !== null && userNormalized === correctNormalized;

            q.isCorrect = isCorrect;
            if (isCorrect) {
                correctCount++;
            }
        });

        this.state.score = correctCount;
        this.state.checked = true;

        const gameResults = this.state.questions.map(q => ({
            question: q.prompt,
            userGuess: q.userAnswer || "(Empty)",
            correctAnswer: q.correctAnswer,
            isCorrect: q.isCorrect,
        }));

        await this.onGameFinished(this.state.score, gameResults, this.state.timer_seconds);
    }

    _buildAnswerHtml(results, elapsedSeconds) {
        const timeDisplay = this.formatTime(elapsedSeconds);
        const rows = results.map(res => {
            const bgColor = res.isCorrect ? "#d4edda" : "#f8d7da";
            const textColor = res.isCorrect ? "#155724" : "#721c24";

            return `
                <tr>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.question}</td>
                    <td style="padding: 8px; border: 1px solid #dee2e6; background-color: ${bgColor}; color: ${textColor}; font-weight: bold;">
                        ${res.userGuess}
                    </td>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.correctAnswer}</td>
                </tr>`;
        }).join("");

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

    async onGameFinished(finalScore, gameResults, elapsedSeconds) {
        if (!this.isValidSubmission) {
            this.notification.add(
                `Practice Score: ${finalScore} out of ${this.state.questions.length} (Time: ${this.formatTime(elapsedSeconds)})`,
                { type: "info" }
            );
            return;
        }

        if (this.state.submission_state !== "assigned") {
            this.notification.add("This task has already been submitted so these results can not be saved.", { type: "info" });
            return;
        }

        const htmlReport = this._buildAnswerHtml(gameResults, elapsedSeconds);
        const hours = Math.round((elapsedSeconds / 3600) * 10) / 10;

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
    }
}

registry.category("actions").add("action_binary_conversions_js", BinaryConversionsGame);

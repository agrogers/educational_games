/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LonelySGame extends Component {
    static template = "lonely_s_game.GameTemplate";
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
            submitted: false, 
            score: 0,
            totalDifficulty: 0,
            sentences: [],
            submission_state: context.submission_state,
            submission_submitted: false

        });
        
        this.resId = context.active_id;
        this.resModel = context.active_model;
        this.submissionModel = "aps.resource.submission";
        this.isValidSubmission = (this.resModel === this.submissionModel && !!this.resId);
        this.numSentences = context.out_of_marks || 10; // default for practice mode
        

        this.generateNewGame();
    }

    async generateNewGame() {
        this.state.loading = true;
        this.state.checked = false;
        this.state.submission_submitted = false;
        try {
            const result = await this.orm.call("game.data", "get_lonely_s_sentences", [this.numSentences, null]);
            console.log('Backend result:', result);
            this.state.sentences = result.map((s, index) => ({
                ...s,
                uniqueId: index,
                userAnswer: "",
                isCorrect: null
            }));
            this.state.totalDifficulty = result.reduce((sum, s) => sum + (s.difficulty || 0), 0);
        } catch (error) {
            console.error("Error in generateNewGame:", error);
        } finally {
            this.state.loading = false;
        }
        // Creates five new sentences in the background. This keeps happening until we have a 1000 sentences.
        this.orm.call("game.data", "generate_sentences_ai", [5]);  
    }

    async checkAnswers() {
        let correctCount = 0;
        
        // 1. Calculate correctness for each sentence
        this.state.sentences.forEach(s => {
            const normalize = (str) => str.replace(/[,;\/]/g, ' ').split(/\s+/).map(w => w.trim().toLowerCase()).filter(w => w).sort();
            const userWords = normalize(s.userAnswer);
            const correctWords = normalize(s.correctWords);
            
            const isMatch = userWords.length === correctWords.length && userWords.every((w, i) => w === correctWords[i]);
            if (isMatch) correctCount++;
            s.isCorrect = isMatch;
        });

        this.state.score = correctCount;
        this.state.checked = true;

        // 2. Map the state to the format expected by the HTML builder
        const gameResults = this.state.sentences.map(s => ({
            originalText: s.text,
            userGuess: s.userAnswer || "(Empty)",
            correctVerb: s.correctWords,
            isCorrect: s.isCorrect
        }));

        // 3. Trigger the submission logic
        await this.onGameFinished(this.state.score, gameResults);
    }

    _buildAnswerHtml(results) {
        let rows = results.map(res => {
            const bgColor = res.isCorrect ? "#d4edda" : "#f8d7da";
            const textColor = res.isCorrect ? "#155724" : "#721c24";
            const feedback = res.isCorrect ? "" : `<br/><small>Correct: ${res.correctVerb}</small>`;
            
            return `
                <tr>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.originalText}</td>
                    <td style="padding: 8px; border: 1px solid #dee2e6; background-color: ${bgColor}; color: ${textColor}; font-weight: bold;">
                        ${res.userGuess}
                    </td>
                    <td style="padding: 8px; border: 1px solid #dee2e6;">${res.correctVerb}</td>
                </tr>`;
        }).join("");

        return `
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
            this.notification.add(`Practice Score: ${finalScore} out of ${this.numSentences} `, { type: "info" });
            return; // Don't close immediately in practice so they can see results
        }

        if (this.state.submission_state != 'assigned') {
            this.notification.add("This task has already been submitted so these results can not be saved.", { type: "info" });
            return;
        }

        const htmlReport = this._buildAnswerHtml(gameResults);

        try {
            await this.orm.write(this.submissionModel, [this.resId], {
                score: finalScore,
                answer: htmlReport,
                state: 'submitted'
            });
            this.notification.add("Official submission saved!", { type: "success" });
            this.state.submission_state = 'submitted';
            this.state.submission_submitted = true;

        } catch (error) {
            this.notification.add("Error saving submission.", { type: "danger" });
        }
    }

    async flagProblem(uniqueId) {
        const sentence = this.state.sentences.find(s => s.uniqueId === uniqueId);
        console.log('Found sentence:', sentence);
        if (sentence && sentence.record_id) {
            try {
                await this.orm.write("game.data", [sentence.record_id], { problem_flag: true });
                this.notification.add("Question flagged as problematic.", { type: "info" });
            } catch (error) {
                console.error("Error flagging question:", error);
                this.notification.add("Error flagging question.", { type: "danger" });
            }
        } else {
            console.log('Sentence not found or no record_id');
        }
    }
    resetGame() {
        this.generateNewGame();
    }
}

registry.category("actions").add("action_lonely_s_game_js", LonelySGame);
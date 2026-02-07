/** @odoo-module **/
// import { Component, useState } from "@odoo/owl";
/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LonelySGame extends Component {
    static template = "lonely_s_game.GameTemplate";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            checked: false,
            score: 0,
            totalDifficulty: 0,
            sentences: []
        });
        // Generate first game on load
        this.generateNewGame();
    }

    async generateNewGame() {
        this.state.loading = true;
        this.state.checked = false;
        try {
            // This calls the Python method to get sentences
            const result = await this.orm.call("game.data", "get_lonely_s_sentences", [10, null]);
            const totalDifficulty = result.reduce((sum, s) => sum + (s.difficulty || 0), 0);
            this.state.sentences = result.map((s, index) => ({
                ...s,
                uniqueId: index,
                userAnswer: "",
                isCorrect: null
            }));
            this.state.totalDifficulty = totalDifficulty;
        } catch (error) {
            this.notification.add(`Error: ${error.data.message}`, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async checkAnswers() {
        let correctCount = 0;
        this.state.sentences.forEach(s => {
            const normalizeWords = (str) => str.replace(/[,;\/]/g, ' ').split(/\s+/).map(w => w.trim().toLowerCase()).filter(w => w).sort();
            const userWords = normalizeWords(s.userAnswer);
            const correctWords = normalizeWords(s.correctWords);
            const isMatch = userWords.length === correctWords.length && userWords.every((w, i) => w === correctWords[i]);
            if (isMatch) correctCount++;
            s.isCorrect = isMatch;
        });

        this.state.score = Math.round((correctCount / this.state.sentences.length) * 100);
        this.state.checked = true;

        await this.orm.call("game.result", "save_score", [this.state.score]);
        this.notification.add(`Game Finished! Score: ${this.state.score}%`, { type: "success" });
    }

    resetGame() {
        this.generateNewGame();
    }
}

registry.category("actions").add("action_lonely_s_game_js", LonelySGame);
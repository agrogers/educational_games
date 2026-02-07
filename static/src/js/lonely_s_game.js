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
            checked: false,
            score: 0,
            sentences: [
                { id: 1, text: "He walk to school every day.", correctWord: "walks", userAnswer: "" },
                { id: 2, text: "She like eating apples.", correctWord: "likes", userAnswer: "" },
                { id: 3, text: "The cat sleep on the rug.", correctWord: "sleeps", userAnswer: "" },
                { id: 4, text: "My brother play football.", correctWord: "plays", userAnswer: "" },
                { id: 5, text: "It rain a lot in Seattle.", correctWord: "rains", userAnswer: "" },
                { id: 6, text: "The teacher speak very fast.", correctWord: "speaks", userAnswer: "" },
                { id: 7, text: "He never listen to me.", correctWord: "listens", userAnswer: "" },
                { id: 8, text: "The sun rise in the east.", correctWord: "rises", userAnswer: "" },
                { id: 9, text: "This cake taste delicious.", correctWord: "tastes", userAnswer: "" },
                { id: 10, text: "She watch TV every night.", correctWord: "watches", userAnswer: "" },
            ]
        });
    }

    async checkAnswers() {
        let correctCount = 0;
        this.state.sentences.forEach(s => {
            if (s.userAnswer.trim().toLowerCase() === s.correctWord.toLowerCase()) {
                correctCount++;
            }
        });

        this.state.score = (correctCount / this.state.sentences.length) * 100;
        this.state.checked = true;

        // Save to Odoo Database
        try {
            await this.orm.call("game.result", "save_score", [this.state.score]);
            this.notification.add(`Results saved: ${this.state.score}%`, { type: "info" });
        } catch (error) {
            this.notification.add("Could not save score.", { type: "danger" });
        }
    }

    resetGame() {
        this.state.checked = false;
        this.state.score = 0;
        this.state.sentences.forEach(s => s.userAnswer = "");
    }
}

registry.category("actions").add("action_lonely_s_game_js", LonelySGame);
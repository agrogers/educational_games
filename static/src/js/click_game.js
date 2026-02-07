odoo.define('educational_games.click_game', ['@web/legacy/js/public/public_widget'], function (publicWidget) {
    'use strict';

    publicWidget.registry.ClickGame = publicWidget.Widget.extend({
        selector: '#click-game-container',
        events: {
            'click #click-button': '_onClickButton',
        },
        init: function () {
            this._super.apply(this, arguments);
            this.clicks = 0;
            this.timeLeft = 10;
            this.gameRunning = false;
        },
        start: function () {
            this._super.apply(this, arguments);
            this._updateDisplay();
        },
        _onClickButton: function () {
            if (!this.gameRunning) {
                this._startGame();
            } else {
                this.clicks++;
                this._updateDisplay();
            }
        },
        _startGame: function () {
            this.gameRunning = true;
            this.clicks = 0;
            this.timeLeft = 10;
            this._updateDisplay();
            this.$('#click-button').text('Click Me!');
            this.$('#message').text('');

            this.timer = setInterval(() => {
                this.timeLeft--;
                this._updateDisplay();
                if (this.timeLeft <= 0) {
                    this._endGame();
                }
            }, 1000);
        },
        _endGame: function () {
            this.gameRunning = false;
            clearInterval(this.timer);
            this.$('#click-button').text('Start Again');
            this.$('#message').text('Game Over! You clicked ' + this.clicks + ' times.');
        },
        _updateDisplay: function () {
            this.$('#score').text('Clicks: ' + this.clicks);
            this.$('#time').text('Time: ' + this.timeLeft);
        },
    });
});
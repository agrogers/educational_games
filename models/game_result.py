from odoo import models, fields, api
import requests
import json

class GameResult(models.Model):
    _name = 'game.result'
    _description = 'Student Game Scores'

    student_id = fields.Many2one('res.users', string="Student", default=lambda self: self.env.user)
    score = fields.Integer("Final Score")
    game_data = fields.Json("Raw Game Logs") # Store JSON for detailed analysis
    processed = fields.Boolean("Synced to LMS", default=False)

    @api.model
    def save_score(self, score, logs=None):
        # Business logic: Create record and perhaps trigger LMS update
        return self.create({
            'score': score,
            'game_data': logs,
            'student_id': self.env.uid,
        }).id
    



    @api.model
    def generate_sentences_ai(self):
        # Hugging Face Free API URL
        API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        # Get your free token from huggingface.co/settings/tokens
        headers = {"Authorization": "Bearer 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"}

        prompt = (
            "Generate 10 English sentences where the third-person singular 's' is missing. "
            "Return ONLY a JSON list like this: "
            "[{\"id\": 1, \"text\": \"He run fast\", \"correctWord\": \"runs\"}]"
        )

        try:
            response = requests.post(API_URL, headers=headers, json={"inputs": prompt})
            content = response.json()
            
            # Extract text from the AI's response
            generated_text = content[0]['generated_text']
            # We clean the response to find the JSON part
            json_start = generated_text.find('[')
            json_end = generated_text.rfind(']') + 1
            return json.loads(generated_text[json_start:json_end])
        except Exception as e:
            # Fallback data if API is down
            return [{"id": 1, "text": "The sun shine bright.", "correctWord": "shines"}]    
from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
import json
import random

class GameData(models.Model):
    _name = 'game.data'
    _description = 'Game Data'

    game_name = fields.Char(string='Game Name', required=True)
    data_category = fields.Char(string='Data Category', required=True)
    json_data = fields.Json(string='JSON Data')
    difficulty = fields.Integer(string='Difficulty', default=0)
    usage = fields.Integer(string='Usage', default=0)
    problem_flag = fields.Boolean(string='Problem Flag', default=False)

    @api.constrains('difficulty')
    def _check_difficulty(self):
        for record in self:
            if not (0 <= record.difficulty <= 10):
                raise ValueError("Difficulty must be between 0 and 10")

    @api.model
    def get_lonely_s_sentences(self, num_sentences=10, difficulty_level=None):
        domain = [('game_name', '=', 'Lonely S'), ('data_category', '=', 'sentence')]
        all_ids = self.search(domain).ids
        if not all_ids:
            # If no records, generate some first
            self.generate_sentences_ai(40)
            all_ids = self.search(domain).ids
        
        if difficulty_level is not None:
            # Filter IDs by difficulty
            all_records = self.browse(all_ids)
            candidate_ids = [r.id for r in all_records if abs(r.difficulty - difficulty_level) <= 2]
        else:
            candidate_ids = all_ids
        
        # Shuffle the candidate IDs
        random.shuffle(candidate_ids)
        # Get the first num_sentences
        selected_ids = candidate_ids[:num_sentences]
        selected_records = self.browse(selected_ids)
        
        sentences = []
        for record in selected_records:
            data = record.json_data.copy()
            data['correctWords'] = data.get('correctWords') or data.get('correctWords', '')            
            data['difficulty'] = record.difficulty
            data['record_id'] = record.id            
            sentences.append(data)            # Increment usage
            record.usage += 1        
        # After getting sentences, generate more if needed
        if len(sentences) < num_sentences:
            self.generate_sentences_ai(max(10, num_sentences - len(sentences)))
        
        return sentences   
                
    @api.model
    def generate_sentences_ai(self, num_sentences=2, sentence_count_limit=10):
        """
        Generates grammar sentences using a fast model (8B) and 
        verifies them using a smart model (70B) for 100% accuracy.
        """        # Check if we have reached the sentence limit
        domain = [('game_name', '=', 'Lonely S'), ('data_category', '=', 'sentence')]
        if self.search_count(domain) >= sentence_count_limit:
            return []  # Do not generate more
                # 1. Fetch Configuration
        icp_sudo = self.env['ir.config_parameter'].sudo()
        api_key = icp_sudo.get_param('groq.api_key')
        if not api_key:
            raise UserError("Please configure 'groq.api_key' in System Parameters.")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }


        # --- STEP 1: Generate Correct "Seed" Sentences ---
        if num_sentences < 3:
            category = random.choice(["4-8 words", "9-15 words", "16-25 words"])
            sentence_lengths = f"Generate {num_sentences} sentences with {category}."
        else:
            base = num_sentences // 3
            extra = num_sentences % 3
            counts = [base] * 3
            for i in range(extra):
                counts[i] += 1
            sentence_lengths = f"Generate {counts[0]} sentences with 4-8 words, {counts[1]} sentences with 9-15 words, {counts[2]} sentences with 16-25 words."
        
        seed_prompt = (
            f"Generate {num_sentences} diverse English sentences in third-person singular. "
            f"{sentence_lengths} "
            "Include a mix of simple, compound, and complex sentences. "
            "Use mostly singular subjects but occasionally include  plural subjects."
            "Include different sentence types like statements and questions. "
            "Every sentence MUST end with exactly one appropriate terminal mark (period, question mark, or exclamation point)."
            "Example: 'He runs fast.'; 'Why does she run fast?'; 'She walks to the library every single afternoon because she wants to study for her final history exam."
            "Return a JSON object with EXACTLY one key called 'sentences' which contains the list of sentences. "
            "Structure: {'sentences': [{'id': 1, 'text': '...'} etc]}"
        )
        seed_res = requests.post(url, headers=headers, json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": seed_prompt}],
            "response_format": {"type": "json_object"}
        }).json()
        seeds = json.loads(seed_res['choices'][0]['message']['content']).get('sentences', [])

        # --- STEP 2: The Saboteur Pass ---
        saboteur_prompt = """
            Act as a 'Grammar Saboteur'. Review these sentences and create 'Broken' versions.
            Rules: 
            - Subject Singular? Remove the 's' (He eats -> He eat).
            - Subject Plural? Add an 's' (They eat -> They eats).
            - Switch do/does
            - Remove 's' from the main verb but do NOT do it if the resulting word is misspelled (She eats fish -> She eat fish).
            - Add 's' to the main verb but do NOT do it if the resulting word is misspelled (They eat fish -> They eats fish).
            - Any words that end in 's' or could end in 's' should be sabotaged.
            - Do NOT sabotage in a way that creates spelling mistakes. 
            - Sabotage to create grammatical errors ONLY.
            - 'correctWords' must be the word(s) that fixes the error.
            - Sabotage one word only.
            - Return ONLY JSON array with keys: id, text, correctWords. 
            - Structure: {'sentences': [{'id': 1, 'text': '...'} etc]}
                Example: [{'id': 1, 'text': 'He run fast.', 'correctWords': 'runs'}]
                Example: [{'id': 2, 'text': 'Why do she run fast and they walks slow?', 'correctWords': 'does, walk'}]
                Example: [{'id': 3, 'text': 'It runs fast.', 'correctWords': ''}]
            Process these sentences: """ + f"{json.dumps(seeds)}"
        
        saboteur_res = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": saboteur_prompt}],
            "response_format": {"type": "json_object"}
        }
        
        try:
            # First API Call
            response = requests.post(url, headers=headers, json=saboteur_res, timeout=10)
            response.raise_for_status()
            raw_content = response.json()['choices'][0]['message']['content']
            
            # Flexible JSON parsing
            data = json.loads(raw_content)
            sentences = data if isinstance(data, list) else data.get('sentences', [])

            created_records = []
            
            for sentence in sentences:
                text = sentence.get('text', '')
                correct_words = sentence.get('correctWords', '')

                word_count = len(text.split())
                correction_count = len(correct_words.split(','))
                if word_count < 30 and correction_count==1:  # sometimes the model generates very long sentences; ignore those
                    # Formula: (Words * Corrections * 2) / 10, capped at 10
                    difficulty = min(10, (word_count * 2) // 5)

                    record = self.create({
                        'game_name': 'Lonely S',
                        'data_category': 'sentence',
                        'json_data': sentence,
                        'difficulty': difficulty,
                        'usage': 0
                    })
                    created_records.append(record.id)
                
                # Stop if we have reached the requested count
                if len(created_records) >= num_sentences:
                    break

            return created_records

        except Exception as e:
            raise UserError(f"AI Service Error: {str(e)}")
        except requests.exceptions.Timeout:
            raise UserError("The AI request timed out. Please try again later.")
        except requests.exceptions.RequestException as e:
            raise UserError(f"Failed to connect to the AI service: {repr(e)}")
        except json.JSONDecodeError as e:
            raise UserError(f"Received invalid response from the AI service: {repr(e)}")
        except Exception as e:
            raise UserError(f"An unexpected error occurred while generating sentences: {repr(e)}")
    
         
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

    @api.constrains('difficulty')
    def _check_difficulty(self):
        for record in self:
            if not (0 <= record.difficulty <= 10):
                raise ValueError("Difficulty must be between 0 and 10")

    @api.model
    def get_lonely_s_sentences(self, num_sentences=10, difficulty_level=None):
        domain = [('game_name', '=', 'Lonely S'), ('data_category', '=', 'sentence')]
        records = self.search(domain, order='usage asc')
        if not records:
            # If no records, generate some first
            self.generate_sentences_ai(10)
            records = self.search(domain, order='usage asc')
        
        if difficulty_level is not None:
            # Get records with difficulty close to requested (within 2)
            filtered_records = records.filtered(lambda r: abs(r.difficulty - difficulty_level) <= 2)
            selected_records = filtered_records[:num_sentences] if len(filtered_records) >= num_sentences else filtered_records
        else:
            selected_records = records[:num_sentences] if len(records) >= num_sentences else records
        
        sentences = []
        for record in selected_records:
            data = record.json_data.copy()
            data['correctWords'] = data.get('correctWords') or data.get('correctWords', '')            
            data['difficulty'] = record.difficulty            
            sentences.append(data)            # Increment usage
            record.usage += 1        
        # After getting sentences, generate more if needed
        if len(sentences) < num_sentences:
            self.generate_sentences_ai(max(10, num_sentences - len(sentences)))
        
        return sentences   
                
    @api.model
    def generate_sentences_ai(self, num_sentences=2):
        """
        Generates grammar sentences using a fast model (8B) and 
        verifies them using a smart model (70B) for 100% accuracy.
        """
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

        # --- STEP A: GENERATE (The Teacher) ---
        gen_prompt = (
            f"You are an English teacher. Generate {num_sentences * 2} sentences "
            "where 3rd person singular 's' is missing or has been added incorrectly. "
            "Vary complexity from very short sentences to long sentences. "
            "Include sentences with multiple missing 's' verbs. "
            "Include some correct sentences where there are no mistakes. "
            "Return ONLY JSON array with keys: id, text, correctWords. "
            "Example: [{'id': 1, 'text': 'He run fast.', 'correctWords': 'runs'}]"
            "Example: [{'id': 2, 'text': 'What did she runs fast?', 'correctWords': 'run'}]"
            "Example: [{'id': 3, 'text': 'It runs fast.', 'correctWords': ''}]"
        )
        
        gen_data = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": gen_prompt}],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }

        try:
            # First API Call
            response = requests.post(url, headers=headers, json=gen_data, timeout=10)
            response.raise_for_status()
            raw_content = response.json()['choices'][0]['message']['content']
            
            # Flexible JSON parsing
            data = json.loads(raw_content)
            sentences = data if isinstance(data, list) else data.get('sentences', [])

            created_records = []
            
            for sentence in sentences:
                text = sentence.get('text', '')
                correct_words = sentence.get('correctWords', '')

                # --- STEP B: VERIFY (The Binary Judge) ---
                # We ask for a single token: '1' for pass, '0' for fail.
                check_prompt = f"""Task: Grammar Validation
                    Rule: Respond '1' only if '{correct_words}' provides the correct changes for the sentence: '{text}'.
                    Examples:
                    'He go.' | 'goes' | Result: 1
                    'They plays.' | 'play' | Result: 1
                    'He runs.' | '' | Result: 1
                    'She runs.' | 'run' | Result: 0
                    Now evaluate:
                    Sentence: '{text}' | Verb: '{correct_words}' | Result:"""

                judge_data = {
                    "model": "openai/gpt-oss-20b",
                    "messages": [{"role": "user", "content": check_prompt}],
                    "temperature": 0.1,
                    # "max_tokens": 1  # Efficiency: only 1 token output
                }

                # Second API Call (Verification)
                check_res = requests.post(url, headers=headers, json=judge_data, timeout=5)
                verdict = check_res.json()['choices'][0]['message']['content'].strip()

                if verdict != "1":
                    continue # Skip flawed sentences

                # --- STEP C: CALCULATE DIFFICULTY & SAVE ---
                word_count = len(text.split())
                correction_count = len(correct_words.split(','))
                # Formula: (Words * Corrections * 2) / 10, capped at 10
                difficulty = min(10, (word_count * correction_count * 2) // 10)

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
    
         
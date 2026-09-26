import hashlib
import json
import logging

from psycopg2.extensions import adapt

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools import html2plaintext


_logger = logging.getLogger(__name__)
_EMBEDDING_TABLE = 'educational_games_question_embedding'
_INDEX_BATCH_SIZE = 32
_MAX_TOOL_LIMIT = 8
_MAX_TOOL_RESULT_SIZE = 56000
_MAX_INDEXED_TEXT_LENGTH = 12000


class QuizQuestionEmbeddingService(models.AbstractModel):
    _name = 'quiz.question.embedding.service'
    _description = 'Quiz Question Embedding Service'

    @api.model
    def _question_comparison_text(self, question):
        parts = [html2plaintext(question.question_text or '').strip()]
        for answer in question.answer_ids.sorted(key=lambda item: (item.sequence, item.id)):
            answer_text = html2plaintext(answer.answer_text or '').strip()
            if answer_text:
                label = _('Correct answer') if answer.is_correct else _('Incorrect answer')
                parts.append('%s: %s' % (label, answer_text))
        parts.append(_('Marks: %s') % question.marks)
        if question.allow_multiple:
            parts.append(_('Multiple answers are allowed.'))
        normalized = '\n'.join(' '.join(part.split()) for part in parts if part)
        return normalized[:_MAX_INDEXED_TEXT_LENGTH]

    @api.model
    def _question_content_hash(self, question):
        content = self._question_comparison_text(question)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @api.model
    def _question_payload(self, question):
        answer_options = []
        for answer in question.answer_ids.sorted(key=lambda item: (item.sequence, item.id))[:8]:
            answer_options.append({
                'text': html2plaintext(answer.answer_text or '').strip()[:150],
                'is_correct': bool(answer.is_correct),
            })
        quiz_records = (question.all_quiz_ids | question.quiz_id).sorted('id')
        return {
            'id': question.id,
            'question_text': html2plaintext(question.question_text or '').strip()[:1500],
            'marks': question.marks,
            'allow_multiple': bool(question.allow_multiple),
            'answers': answer_options,
            'quizzes': [
                {'id': quiz.id, 'name': (quiz.display_name or '')[:120]}
                for quiz in quiz_records[:4]
            ],
            'subjects': [
                (subject.display_name or '')[:120]
                for subject in question.subject_ids.sorted('id')[:4]
            ],
        }

    @api.model
    def _get_embedding_configuration(self):
        configurations = self.env['aps.ai.provider.embedding'].sudo().search([
            ('provider_id.active', '=', True),
            ('provider_id.enabled', '=', True),
            ('provider_id.provider_type', '=', 'openai'),
        ])
        configuration = configurations.sorted(
            key=lambda item: (-item.provider_id.priority, item.id)
        )[:1]
        if not configuration:
            raise UserError(_('Configure an embedding model on an enabled APS AI provider first.'))
        return configuration[0]

    @api.model
    def _ensure_pgvector_schema(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('CREATE EXTENSION IF NOT EXISTS vector')
        except Exception:
            raise UserError(_(
                'Semantic question search requires the PostgreSQL pgvector extension. '
                'Install pgvector on the database server and enable the vector extension.'
            ))

        self.env.cr.execute(f'''
            CREATE TABLE IF NOT EXISTS {_EMBEDDING_TABLE} (
                question_id INTEGER PRIMARY KEY REFERENCES quiz_question(id) ON DELETE CASCADE,
                provider_id INTEGER NOT NULL REFERENCES aps_ai_provider(id) ON DELETE CASCADE,
                embedding_model VARCHAR NOT NULL,
                embedding_dimensions INTEGER NOT NULL,
                content_hash VARCHAR NOT NULL,
                embedding vector NOT NULL
            )
        ''')
        self.env.cr.execute(f'''
            CREATE INDEX IF NOT EXISTS {_EMBEDDING_TABLE}_config_idx
            ON {_EMBEDDING_TABLE} (provider_id, embedding_model, embedding_dimensions)
        ''')

    @api.model
    def _ensure_hnsw_index(self, configuration):
        dimensions = configuration.embedding_dimensions
        provider_id = configuration.provider_id.id
        index_key = '%s:%s:%s' % (provider_id, configuration.embedding_model, dimensions)
        index_name = '%s_hnsw_%s' % (
            _EMBEDDING_TABLE,
            hashlib.sha256(index_key.encode('utf-8')).hexdigest()[:12],
        )
        quoted_model = adapt(configuration.embedding_model).getquoted().decode('utf-8')
        self.env.cr.execute(f'''
            CREATE INDEX IF NOT EXISTS "{index_name}"
            ON {_EMBEDDING_TABLE}
            USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
            WHERE provider_id = {provider_id}
                AND embedding_model = {quoted_model}
                AND embedding_dimensions = {dimensions}
        ''')

    @api.model
    def _vector_literal(self, vector):
        return '[%s]' % ','.join(format(value, '.17g') for value in vector)

    @api.model
    def _index_questions(self, questions, configuration):
        if not questions:
            return 0
        comparison_texts = [self._question_comparison_text(question) for question in questions]
        vectors = configuration._create_embeddings(comparison_texts)
        for question, content, vector in zip(questions, comparison_texts, vectors):
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            self.env.cr.execute(f'''
                INSERT INTO {_EMBEDDING_TABLE} (
                    question_id, provider_id, embedding_model, embedding_dimensions,
                    content_hash, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (question_id) DO UPDATE SET
                    provider_id = EXCLUDED.provider_id,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dimensions = EXCLUDED.embedding_dimensions,
                    content_hash = EXCLUDED.content_hash,
                    embedding = EXCLUDED.embedding
            ''', (
                question.id,
                configuration.provider_id.id,
                configuration.embedding_model,
                configuration.embedding_dimensions,
                content_hash,
                self._vector_literal(vector),
            ))
        self._ensure_hnsw_index(configuration)
        return len(questions)

    @api.model
    def _question_has_current_embedding(self, question, configuration):
        content_hash = self._question_content_hash(question)
        self.env.cr.execute(f'''
            SELECT 1
            FROM {_EMBEDDING_TABLE}
            WHERE question_id = %s
                AND provider_id = %s
                AND embedding_model = %s
                AND embedding_dimensions = %s
                AND content_hash = %s
        ''', (
            question.id,
            configuration.provider_id.id,
            configuration.embedding_model,
            configuration.embedding_dimensions,
            content_hash,
        ))
        return bool(self.env.cr.fetchone())

    @api.model
    def _pending_question_ids(self, configuration, limit, preferred_question_id=None):
        order_sql = 'question.id'
        params = [
            configuration.provider_id.id,
            configuration.embedding_model,
            configuration.embedding_dimensions,
        ]
        if preferred_question_id:
            order_sql = 'CASE WHEN question.id = %s THEN 0 ELSE 1 END, question.id'
            params.append(preferred_question_id)
        params.append(limit)
        self.env.cr.execute(f'''
            SELECT question.id
            FROM quiz_question AS question
            LEFT JOIN {_EMBEDDING_TABLE} AS embedding
                ON embedding.question_id = question.id
            WHERE embedding.question_id IS NULL
                OR embedding.provider_id != %s
                OR embedding.embedding_model != %s
                OR embedding.embedding_dimensions != %s
            ORDER BY {order_sql}
            LIMIT %s
        ''', params)
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def _pending_question_count(self, configuration):
        self.env.cr.execute(f'''
            SELECT COUNT(*)
            FROM quiz_question AS question
            LEFT JOIN {_EMBEDDING_TABLE} AS embedding
                ON embedding.question_id = question.id
            WHERE embedding.question_id IS NULL
                OR embedding.provider_id != %s
                OR embedding.embedding_model != %s
                OR embedding.embedding_dimensions != %s
        ''', (
            configuration.provider_id.id,
            configuration.embedding_model,
            configuration.embedding_dimensions,
        ))
        return self.env.cr.fetchone()[0]

    @api.model
    def _invalidate_question_ids(self, question_ids):
        question_ids = list(set(question_ids or []))
        if not question_ids:
            return
        self.env.cr.execute('SELECT to_regclass(%s)', (_EMBEDDING_TABLE,))
        if self.env.cr.fetchone()[0]:
            self.env.cr.execute(
                f'DELETE FROM {_EMBEDDING_TABLE} WHERE question_id = ANY(%s)',
                (question_ids,),
            )

    @api.model
    def _cron_index_pending_questions(self):
        configurations = self.env['aps.ai.provider.embedding'].sudo().search([
            ('provider_id.active', '=', True),
            ('provider_id.enabled', '=', True),
            ('provider_id.provider_type', '=', 'openai'),
        ])
        configuration = configurations.sorted(
            key=lambda item: (-item.provider_id.priority, item.id)
        )[:1]
        if not configuration:
            return 0
        configuration = configuration[0]
        self.env.cr.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
        )
        if not self.env.cr.fetchone():
            return 0
        self._ensure_pgvector_schema()
        question_ids = self._pending_question_ids(configuration, _INDEX_BATCH_SIZE)
        if not question_ids:
            return 0
        questions = self.env['quiz.question'].sudo().search([('id', 'in', question_ids)])
        return self._index_questions(questions, configuration)

    @api.model
    def _find_likely_duplicates(self, question_id, quiz_id=None, limit=10):
        if type(question_id) is not int or question_id <= 0:
            raise ValidationError(_('Question ID must be a positive integer.'))
        if quiz_id is not None and (type(quiz_id) is not int or quiz_id <= 0):
            raise ValidationError(_('Quiz ID must be a positive integer.'))
        if type(limit) is not int:
            raise ValidationError(_('Candidate limit must be an integer.'))
        limit = max(1, min(limit, _MAX_TOOL_LIMIT))

        self._ensure_pgvector_schema()
        configuration = self._get_embedding_configuration()
        Question = self.env['quiz.question']
        source = Question.search([('id', '=', question_id)], limit=1)
        if not source:
            raise UserError(_('The source question is missing or is not accessible.'))
        source.check_access('read')
        if quiz_id:
            quiz = self.env['quiz.quiz'].search([('id', '=', quiz_id)], limit=1)
            if not quiz:
                raise UserError(_('The requested quiz is missing or is not accessible.'))

        if not self._question_has_current_embedding(source, configuration):
            self._index_questions(source, configuration)

        pending_count = self._pending_question_count(configuration)
        source_payload = self._question_payload(source)
        if pending_count:
            return {
                'status': 'indexing',
                'pending_count': pending_count,
                'source_question': source_payload,
                'candidates': [],
            }

        self._ensure_hnsw_index(configuration)
        dimensions = configuration.embedding_dimensions
        provider_id = configuration.provider_id.id
        quoted_model = adapt(configuration.embedding_model).getquoted().decode('utf-8')
        self.env.cr.execute(f'''
            SELECT embedding::text
            FROM {_EMBEDDING_TABLE}
            WHERE question_id = %s
                AND provider_id = %s
                AND embedding_model = %s
                AND embedding_dimensions = %s
        ''', (question_id, provider_id, configuration.embedding_model, dimensions))
        source_vector = self.env.cr.fetchone()
        if not source_vector:
            raise UserError(_('The source question could not be indexed.'))

        query = f'''
            SELECT candidate.question_id,
                1 - (candidate.embedding::vector({dimensions}) <=>
                    %s::vector({dimensions})) AS similarity
            FROM {_EMBEDDING_TABLE} AS candidate
            WHERE candidate.provider_id = {provider_id}
                AND candidate.embedding_model = {quoted_model}
                AND candidate.embedding_dimensions = {dimensions}
                AND candidate.question_id != %s
        '''
        params = [source_vector[0], question_id]
        if quiz_id:
            query += '''
                AND EXISTS (
                    SELECT 1
                    FROM quiz_question AS scoped_question
                    WHERE scoped_question.id = candidate.question_id
                        AND (
                            scoped_question.quiz_id = %s
                            OR EXISTS (
                                SELECT 1 FROM quiz_quiz_question_rel AS membership
                                WHERE membership.question_id = scoped_question.id
                                    AND membership.quiz_id = %s
                            )
                        )
                )
            '''
            params.extend([quiz_id, quiz_id])
        query += f'''
            ORDER BY candidate.embedding::vector({dimensions}) <=> %s::vector({dimensions})
            LIMIT %s
        '''
        params.extend([source_vector[0], min(limit * 5, 100)])
        self.env.cr.execute(query, params)
        ranked_rows = self.env.cr.fetchall()
        ranked_ids = [row[0] for row in ranked_rows]
        similarities = {row[0]: round(float(row[1]), 4) for row in ranked_rows}

        candidate_domain = [('id', 'in', ranked_ids)]
        if quiz_id:
            candidate_domain = expression.AND([
                candidate_domain,
                ['|', ('quiz_id', '=', quiz_id), ('all_quiz_ids', 'in', [quiz_id])],
            ])
        accessible_candidates = Question.search(candidate_domain)
        accessible_by_id = {candidate.id: candidate for candidate in accessible_candidates}
        candidate_pool = [
            {
                'similarity': similarities[candidate_id],
                'question': self._question_payload(accessible_by_id[candidate_id]),
            }
            for candidate_id in ranked_ids
            if candidate_id in accessible_by_id
        ]
        candidates = candidate_pool[:limit]
        truncated = len(candidate_pool) > limit
        result = {
            'status': 'ready',
            'source_question': source_payload,
            'candidate_count': len(candidates),
            'candidates': candidates,
            'truncated': truncated,
        }
        while len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > _MAX_TOOL_RESULT_SIZE and candidates:
            candidates.pop()
            result['candidate_count'] = len(candidates)
            result['truncated'] = True
        if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > _MAX_TOOL_RESULT_SIZE:
            result['source_question']['question_text'] = source_payload['question_text'][:500]
            result['source_question']['answers'] = source_payload['answers'][:3]
        if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > _MAX_TOOL_RESULT_SIZE:
            raise ValidationError(_('Question content exceeds the semantic-search tool result limit.'))
        return result
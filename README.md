# Educational Games

## Semantic Quiz Question Search

The APS AI tools `find_likely_duplicate_quiz_questions` and
`merge_confirmed_quiz_question_pair` are available to APEX teachers and
managers. Candidate search is read-only and similarity scores are advisory;
the LLM must review the returned question and answer text before proposing a
merge.

### Setup

1. Install the PostgreSQL `pgvector` package compatible with the database
   server, then enable it in the Odoo database with `CREATE EXTENSION vector;`.
   The database role used by Odoo must be allowed to create the semantic-search
   table and indexes.
2. On an enabled APS AI OpenAI-compatible provider, add an optional Embedding
   Configuration with a model, endpoint path, and vector dimension. The default
   endpoint path is `/embeddings`; configured dimensions must match the model
   output and be between 1 and 2000.
3. Upgrade `educational_games`. The first candidate-search call indexes its
   source question. A five-minute cron indexes remaining questions in batches
   of 32; search reports `status: indexing` until the bank has been indexed.

Question text and answer text are sent to the configured embedding provider.
Use a provider approved for that content. Candidate responses contain plain
text, correctness labels, quiz/subject context, and similarity, but no student
identities or individual responses.

### Merge Behavior

The merge tool requires APS AI confirmation. Its explicit keeper remains the
question whose wording and answer options are retained. Responses on the
duplicate are reassigned to the first keeper answer of matching correctness
(correct to correct, incorrect to incorrect); response rows and their stored
correctness are preserved. The merge is rejected before mutation if a response
uses a correctness class not present on the keeper. Quiz, subject, and tag
memberships are combined, then the duplicate question and its answer options
are deleted.
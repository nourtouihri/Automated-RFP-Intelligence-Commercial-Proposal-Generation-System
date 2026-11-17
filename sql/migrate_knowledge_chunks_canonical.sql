-- Non-destructive migration for an existing knowledge_chunks table.
-- Run this once in Supabase SQL Editor before running rag-ingest.

alter table public.knowledge_chunks
    add column if not exists title text not null default '',
    add column if not exists text text not null default '',
    add column if not exists lang text not null default 'en',
    add column if not exists synthetic boolean not null default false,
    add column if not exists chunk_version text,
    add column if not exists content_hash text;

-- The ingestion code writes both canonical dataset fields and the existing
-- vector-search fields. Refresh PostgREST after changing the table shape.
notify pgrst, 'reload schema';

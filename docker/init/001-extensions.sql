-- Extensões exigidas pela spec (docs/02-data.md).
-- pgvector: busca densa.
CREATE EXTENSION IF NOT EXISTS vector;

-- unaccent: normalização de acentos para o FTS em português.
CREATE EXTENSION IF NOT EXISTS unaccent;

-- pg_trgm: fallback lexical para nome próprio e sigla (ex.: "PLP", "ICMS-ST").
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- `unaccent()` não é IMMUTABLE, então não pode ser usada direto em coluna
-- gerada nem em índice de expressão. Wrapper imutável resolve — sem isso o
-- CREATE INDEX do tsvector falha (armadilha registrada em docs/02-data.md).
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$ SELECT public.unaccent('public.unaccent', $1) $$;

-- Configuração de busca textual em português já com unaccent aplicado.
-- Uso na F0: to_tsvector('pt_unaccent', immutable_unaccent(text)).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'pt_unaccent') THEN
    CREATE TEXT SEARCH CONFIGURATION pt_unaccent (COPY = portuguese);
    ALTER TEXT SEARCH CONFIGURATION pt_unaccent
      ALTER MAPPING FOR hword, hword_part, word
      WITH unaccent, portuguese_stem;
  END IF;
END
$$;

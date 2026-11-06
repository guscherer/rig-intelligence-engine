"""Chunker hierárquico para texto legislativo.

Segmenta por hierarquia real (Art. -> § -> inciso -> alínea), gerando
breadcrumb textual e ``chunk_id`` estável.

Justificativa de tamanho (docs/10 §2): este módulo concentra o parser de
hierarquia legal, as regras de quebra por orçamento de tokens e o id estável;
picar em arquivos rasos perderia o fluxo de uma run. Módulo e funções longas
são esperados aqui.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal["preambulo", "dispositivo", "anexo"]

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

_ARTICLE_RE = re.compile(
    r"(?im)^\s*Art\.?\s+(?P<num>\d+(?:º|°)?(?:-[A-Za-z])?)\s*(?P<vetado>Vetado)?",
)
_CONTAINER_RE = re.compile(
    r"(?im)^\s*(?P<name>T[íi]tulo|Cap[íi]tulo|Se[çc][ãa]o|Subse[çc][ãa]o)\b",
)
_ANEXO_RE = re.compile(r"(?im)^\s*(?P<name>ANEXO|TABELA|QUADRO|ANEXO\s+[IVXLC]+)\b")
_INCISO_RE = re.compile(r"(?m)^\s*(?P<inciso>[IVXLC]+)\s*[-\u2013\u2014]")
_ALINEA_RE = re.compile(r"(?m)^\s*(?P<alinea>[a-z])\)")
_PARA_RE = re.compile(
    r"(?m)^\s*(?P<para>§§?\s*\d+(?:º|°)?(?:\s*e\s*\d+(?:º|°)?)*|Parágrafo único\.?)",
)


class Hierarchy:
    """Hierarquia estruturada com acesso por atributo e por chave."""

    def __init__(
        self,
        artigo: str | None = None,
        paragrafo: str | None = None,
        inciso: str | None = None,
        alinea: str | None = None,
    ) -> None:
        self.artigo = artigo
        self.paragrafo = paragrafo
        self.inciso = inciso
        self.alinea = alinea

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "artigo": self.artigo,
            "paragrafo": self.paragrafo,
            "inciso": self.inciso,
            "alinea": self.alinea,
        }

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.to_dict() == other
        if isinstance(other, Hierarchy):
            return self.to_dict() == other.to_dict()
        return False

    def __hash__(self) -> int:
        return hash((self.artigo, self.paragrafo, self.inciso, self.alinea))


class Chunk(BaseModel):
    """Contrato do chunk (docs/02-data.md §5)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    chunk_id: str
    source: str
    doc_id: str
    doc_type: str
    doc_meta: dict[str, Any]
    breadcrumb: str
    hierarchy: Hierarchy
    kind: Kind
    text: str
    ordinal: int
    char_span: list[int]
    page: int | None = None
    extraction_quality: str = "high"
    content_hash: str


@dataclass
class _Segment:
    hierarchy: Hierarchy
    text: str
    start: int
    end: int
    container: str | None = None


@dataclass
class _Article:
    art_label: str
    container: str | None
    start: int
    end: int
    text: str
    segments: list[_Segment] = field(default_factory=list)


def _roman_to_int(value: str) -> int:
    total = 0
    prev = 0
    for ch in reversed(value.upper()):
        v = _ROMAN_VALUES.get(ch, 0)
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total


def _token_count(text: str) -> int:
    return len(text.split())


def _article_number(label: str) -> str:
    match = re.search(r"\d+", label)
    return match.group(0) if match else label


def _breadcrumb_key(chunk: Chunk) -> str:
    h = chunk.hierarchy
    parts: list[str] = []
    if h.artigo is not None:
        parts.append("a" + _article_number(h.artigo))
    if h.paragrafo is not None:
        pnum = _article_number(h.paragrafo)
        # combined paragraphs keep their raw token
        if not re.search(r"\d", h.paragrafo or ""):
            parts.append(h.paragrafo.lower().replace(" ", ""))
        else:
            parts.append("§" + pnum)
    if h.inciso is not None:
        parts.append("i" + str(_roman_to_int(h.inciso)))
    if h.alinea is not None:
        parts.append(h.alinea.rstrip(")").lower())
    if chunk.kind == "preambulo":
        return "preambulo"
    if chunk.kind == "anexo":
        return "anexo"
    return "".join(parts)


def _make_chunk_id(doc_id: str, breadcrumb_key: str, ordinal: int) -> str:
    return f"cam:{doc_id}:{breadcrumb_key}:{ordinal:02d}"


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _find_articles(text: str) -> list[tuple[int, int, str]]:
    """Retorna lista de (start, end, art_label) para cada artigo."""
    matches = list(_ARTICLE_RE.finditer(text))
    result: list[tuple[int, int, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append((start, end, m.group("num")))
    return result


def _container_at(text: str, pos: int) -> str | None:
    # container mais recente antes de pos
    last: str | None = None
    for m in _CONTAINER_RE.finditer(text):
        if m.start() <= pos:
            last = m.group("name")
        else:
            break
    return last


def _parse_article_segments(article: _Article) -> None:  # noqa: PLR0912, PLR0915  # parser hierárquico; complexidade inerente
    text = article.text
    base_start = article.start
    art_label = article.art_label
    h_base_artigo = f"{art_label}"

    all_markers: list[re.Match[str]] = []
    for m in _PARA_RE.finditer(text):
        all_markers.append(m)
    for m in _INCISO_RE.finditer(text):
        all_markers.append(m)
    for m in _ALINEA_RE.finditer(text):
        all_markers.append(m)
    all_markers.sort(key=lambda m: m.start())

    # dedupe overlapping (same start): prefer para > inciso > alinea
    deduped: list[re.Match[str]] = []
    i = 0
    while i < len(all_markers):
        j = i
        group: list[re.Match[str]] = [all_markers[i]]
        while j + 1 < len(all_markers) and all_markers[j + 1].start() == all_markers[i].start():
            j += 1
            group.append(all_markers[j])
        # pick: para first, then inciso, then alinea
        chosen = None
        for g in group:
            if g.lastgroup == "para":
                chosen = g
                break
        if chosen is None:
            for g in group:
                if g.lastgroup == "inciso":
                    chosen = g
                    break
        if chosen is None:
            chosen = group[0]
        deduped.append(chosen)
        i = j + 1

    # caput: text before first marker
    first_pos = deduped[0].start() if deduped else len(text)
    caput_text = text[:first_pos].strip()
    if caput_text:
        article.segments.append(
            _Segment(
                hierarchy=Hierarchy(artigo=h_base_artigo),
                text=caput_text,
                start=base_start,
                end=base_start + first_pos,
                container=article.container,
            )
        )

    current_para: str | None = None
    current_inciso: str | None = None

    for idx, m in enumerate(deduped):
        seg_start = m.start()
        seg_end = deduped[idx + 1].start() if idx + 1 < len(deduped) else len(text)
        seg_text = text[seg_start:seg_end].strip()
        if not seg_text:
            continue
        if m.lastgroup == "para":
            current_para = m.group("para").strip()
            current_inciso = None
            h = Hierarchy(artigo=h_base_artigo, paragrafo=current_para)
        elif m.lastgroup == "inciso":
            current_inciso = m.group("inciso")
            h = Hierarchy(artigo=h_base_artigo, paragrafo=current_para, inciso=current_inciso)
        else:
            alinea_label = m.group("alinea") + ")"
            h = Hierarchy(
                artigo=h_base_artigo,
                paragrafo=current_para,
                inciso=current_inciso,
                alinea=alinea_label,
            )
        article.segments.append(
            _Segment(
                hierarchy=h,
                text=seg_text,
                start=base_start + seg_start,
                end=base_start + seg_end,
                container=article.container,
            )
        )


def _group_article_chunks(  # noqa: PLR0912, PLR0915  # quebra por orçamento de tokens
    article: _Article,
    quality: str,
    source: str,
    doc_id: str,
    doc_type: str,
    doc_meta: dict[str, Any],
) -> list[Chunk]:
    segments = article.segments
    if not segments:
        return []

    # total article text
    article_text = article.text.strip()
    total_tokens = _token_count(article_text)

    # decide: if whole article fits, one chunk
    if total_tokens <= 512:
        h = Hierarchy(artigo=article.art_label)
        breadcrumb = f"Art. {article.art_label}"
        chunk = Chunk(
            chunk_id="",  # fill later
            source=source,
            doc_id=doc_id,
            doc_type=doc_type,
            doc_meta=doc_meta,
            breadcrumb=breadcrumb,
            hierarchy=h,
            kind="dispositivo",
            text=article_text,
            ordinal=0,
            char_span=[article.start, article.end],
            extraction_quality=quality,
            content_hash=_content_hash(article_text),
        )
        return [chunk]

    # otherwise split
    chunks: list[Chunk] = []

    # caput segment (first with no para/inciso) if exists
    caput_seg = None
    for seg in segments:
        if seg.hierarchy.paragrafo is None and seg.hierarchy.inciso is None:
            caput_seg = seg
            break

    # direct incisos (para None, inciso not None)
    direct_incisos = [
        s for s in segments if s.hierarchy.paragrafo is None and s.hierarchy.inciso is not None
    ]

    # paragraphs groups: each paragraph header + following incisos/alineas until next para
    para_groups: list[list[_Segment]] = []
    current_group: list[_Segment] = []
    for seg in segments:
        if seg.hierarchy.paragrafo is not None and seg is not caput_seg:
            # new paragraph group when para changes
            if current_group and current_group[0].hierarchy.paragrafo != seg.hierarchy.paragrafo:
                para_groups.append(current_group)
                current_group = []
            current_group.append(seg)
        else:
            # non-paragraph segment not in a para group (caput/direct incisos handled separately)
            pass
    if current_group:
        para_groups.append(current_group)

    # caput chunk
    if caput_seg is not None and caput_seg.text.strip():
        # include direct incisos if they fit together with caput
        direct_text = "\n".join(s.text for s in direct_incisos).strip()
        combined_caput = caput_seg.text
        if direct_text:
            combined_caput = caput_seg.text + "\n" + direct_text
        if direct_incisos and _token_count(combined_caput) <= 512:
            h = Hierarchy(artigo=article.art_label)
            chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb=f"Art. {article.art_label}",
                    hierarchy=h,
                    kind="dispositivo",
                    text=combined_caput.strip(),
                    ordinal=0,
                    char_span=[
                        caput_seg.start,
                        (direct_incisos[-1].end if direct_incisos else caput_seg.end),
                    ],
                    extraction_quality=quality,
                    content_hash=_content_hash(combined_caput.strip()),
                )
            )
            direct_incisos = []
        else:
            h = Hierarchy(artigo=article.art_label)
            chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb=f"Art. {article.art_label}",
                    hierarchy=h,
                    kind="dispositivo",
                    text=caput_seg.text,
                    ordinal=0,
                    char_span=[caput_seg.start, caput_seg.end],
                    extraction_quality=quality,
                    content_hash=_content_hash(caput_seg.text),
                )
            )

    # direct incisos individually
    for seg in direct_incisos:
        h = seg.hierarchy
        inc_label = h.inciso or ""
        breadcrumb = f"Art. {article.art_label}, {inc_label}".strip(", ")
        chunks.append(
            Chunk(
                chunk_id="",
                source=source,
                doc_id=doc_id,
                doc_type=doc_type,
                doc_meta=doc_meta,
                breadcrumb=breadcrumb,
                hierarchy=h,
                kind="dispositivo",
                text=seg.text,
                ordinal=0,
                char_span=[seg.start, seg.end],
                extraction_quality=quality,
                content_hash=_content_hash(seg.text),
            )
        )

    # paragraphs
    for group in para_groups:
        if not group:
            continue
        para_label = group[0].hierarchy.paragrafo or ""
        # full paragraph group text
        group_text = "\n".join(s.text for s in group).strip()
        if _token_count(group_text) <= 512:
            h = Hierarchy(artigo=article.art_label, paragrafo=para_label)
            breadcrumb = f"Art. {article.art_label}, {para_label}"
            chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb=breadcrumb,
                    hierarchy=h,
                    kind="dispositivo",
                    text=group_text,
                    ordinal=0,
                    char_span=[group[0].start, group[-1].end],
                    extraction_quality=quality,
                    content_hash=_content_hash(group_text),
                )
            )
            continue
        # split by inciso within paragraph
        # paragraph header (first segment if it's a para marker with no inciso)
        para_header_seg = None
        if group and group[0].hierarchy.inciso is None:
            para_header_seg = group[0]
        if para_header_seg is not None and para_header_seg.text.strip():
            h = Hierarchy(artigo=article.art_label, paragrafo=para_label)
            chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb=f"Art. {article.art_label}, {para_label}",
                    hierarchy=h,
                    kind="dispositivo",
                    text=para_header_seg.text,
                    ordinal=0,
                    char_span=[para_header_seg.start, para_header_seg.end],
                    extraction_quality=quality,
                    content_hash=_content_hash(para_header_seg.text),
                )
            )
        # incisos in this paragraph
        inciso_groups: list[list[_Segment]] = []
        cur: list[_Segment] = []
        for seg in group:
            if seg.hierarchy.inciso is not None:
                if cur and cur[-1].hierarchy.inciso != seg.hierarchy.inciso:
                    inciso_groups.append(cur)
                    cur = []
                cur.append(seg)
            else:
                # para header already handled
                pass
        if cur:
            inciso_groups.append(cur)

        for ig in inciso_groups:
            if not ig:
                continue
            inc_label = ig[0].hierarchy.inciso or ""
            ig_text = "\n".join(s.text for s in ig).strip()
            if _token_count(ig_text) <= 512:
                h = Hierarchy(artigo=article.art_label, paragrafo=para_label, inciso=inc_label)
                breadcrumb = f"Art. {article.art_label}, {para_label}, {inc_label}"
                chunks.append(
                    Chunk(
                        chunk_id="",
                        source=source,
                        doc_id=doc_id,
                        doc_type=doc_type,
                        doc_meta=doc_meta,
                        breadcrumb=breadcrumb,
                        hierarchy=h,
                        kind="dispositivo",
                        text=ig_text,
                        ordinal=0,
                        char_span=[ig[0].start, ig[-1].end],
                        extraction_quality=quality,
                        content_hash=_content_hash(ig_text),
                    )
                )
            else:
                # split by alinea
                alinea_segs = [s for s in ig if s.hierarchy.alinea is not None]
                non_alinea = [s for s in ig if s.hierarchy.alinea is None]
                if non_alinea:
                    text_na = "\n".join(s.text for s in non_alinea).strip()
                    h = Hierarchy(artigo=article.art_label, paragrafo=para_label, inciso=inc_label)
                    chunks.append(
                        Chunk(
                            chunk_id="",
                            source=source,
                            doc_id=doc_id,
                            doc_type=doc_type,
                            doc_meta=doc_meta,
                            breadcrumb=f"Art. {article.art_label}, {para_label}, {inc_label}",
                            hierarchy=h,
                            kind="dispositivo",
                            text=text_na,
                            ordinal=0,
                            char_span=[non_alinea[0].start, non_alinea[-1].end],
                            extraction_quality=quality,
                            content_hash=_content_hash(text_na),
                        )
                    )
                for seg in alinea_segs:
                    alinea_label = seg.hierarchy.alinea or ""
                    h = Hierarchy(
                        artigo=article.art_label,
                        paragrafo=para_label,
                        inciso=inc_label,
                        alinea=alinea_label,
                    )
                    breadcrumb = (
                        f"Art. {article.art_label}, {para_label}, {inc_label}, {alinea_label}"
                    )
                    chunks.append(
                        Chunk(
                            chunk_id="",
                            source=source,
                            doc_id=doc_id,
                            doc_type=doc_type,
                            doc_meta=doc_meta,
                            breadcrumb=breadcrumb,
                            hierarchy=h,
                            kind="dispositivo",
                            text=seg.text,
                            ordinal=0,
                            char_span=[seg.start, seg.end],
                            extraction_quality=quality,
                            content_hash=_content_hash(seg.text),
                        )
                    )

    # filter empty
    result_chunks = [c for c in chunks if c.text.strip()]
    for c in result_chunks:
        if not c.text.strip():
            continue
    return result_chunks


def _build_articles(text: str) -> tuple[str, list[_Article], str]:
    """Retorna (preamble_text, articles, trailing_text)."""
    matches = _find_articles(text)
    anexo_starts = [m.start() for m in _ANEXO_RE.finditer(text)]
    if not matches:
        if anexo_starts:
            first = anexo_starts[0]
            return text[:first].strip(), [], text[first:].strip()
        return text.strip(), [], ""
    first_start = matches[0][0]
    preamble = text[:first_start].strip()
    articles: list[_Article] = []
    for i, (_s, _e, label) in enumerate(matches):
        start = matches[i][0]
        next_art_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        anexo_after = [a for a in anexo_starts if a > start]
        next_anexo = min(anexo_after) if anexo_after else len(text)
        real_end = min(next_art_start, next_anexo)
        container = _container_at(text, start)
        seg_text = text[start:real_end]
        articles.append(
            _Article(
                art_label=label,
                container=container,
                start=start,
                end=real_end,
                text=seg_text,
            )
        )
    last_end = articles[-1].end if articles else len(text)
    trailing = text[last_end:].strip()
    return preamble, articles, trailing


def chunk_document(text: str, doc_meta: dict[str, Any]) -> list[Chunk]:
    """Segmenta texto legislativo em chunks hierárquicos."""
    doc_meta = dict(doc_meta or {})
    doc_id = str(doc_meta.get("doc_id") or doc_meta.get("id") or doc_meta.get("docId") or "")
    source = str(doc_meta.get("source", "camara"))
    doc_type = str(doc_meta.get("doc_type", "proposicao"))
    quality = str(doc_meta.get("extraction_quality", "high"))

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    preamble_text, articles, trailing_text = _build_articles(text)

    all_chunks: list[Chunk] = []

    # preamble
    if preamble_text.strip():
        for part in _split_paragraphs(preamble_text):
            if not part.strip():
                continue
            all_chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb="Preambulo",
                    hierarchy=Hierarchy(),
                    kind="preambulo",
                    text=part,
                    ordinal=0,
                    char_span=[text.find(part), text.find(part) + len(part)],
                    extraction_quality=quality,
                    content_hash=_content_hash(part),
                )
            )

    # articles
    prev_container: str | None = None
    for article in articles:
        # parse segments
        _parse_article_segments(article)
        article_chunks = _group_article_chunks(article, quality, source, doc_id, doc_type, doc_meta)

        # overlap at container boundary
        overlap_condition = (
            article.container is not None
            and article.container != prev_container
            and prev_container is not None
            and bool(all_chunks)
        )
        if overlap_condition:
            last_text = all_chunks[-1].text
            tokens = last_text.split()
            tail = " ".join(tokens[-80:]) if len(tokens) > 80 else last_text
            if article_chunks:
                first = article_chunks[0]
                new_text = (tail + "\n" + first.text).strip()
                # rebuild chunk with overlapped text
                article_chunks[0] = first.model_copy(
                    update={"text": new_text, "content_hash": _content_hash(new_text)}
                )

        all_chunks.extend(article_chunks)
        prev_container = article.container

    # trailing anexo
    if trailing_text.strip():
        # detect anexo vs preambulo: if trailing after articles, treat as anexo
        kind: Kind = "anexo"
        for part in _split_paragraphs(trailing_text):
            if not part.strip():
                continue
            all_chunks.append(
                Chunk(
                    chunk_id="",
                    source=source,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    doc_meta=doc_meta,
                    breadcrumb="Anexo",
                    hierarchy=Hierarchy(),
                    kind=kind,
                    text=part,
                    ordinal=0,
                    char_span=[text.find(part), text.find(part) + len(part)],
                    extraction_quality=quality,
                    content_hash=_content_hash(part),
                )
            )

    # if no articles and no chunks (empty text), still no empty chunks
    # assign ordinals and chunk_ids
    final: list[Chunk] = []
    for i, c in enumerate(all_chunks, start=1):
        if not c.text.strip():
            continue
        key = _breadcrumb_key(c)
        cid = _make_chunk_id(doc_id, key, i)
        updated = c.model_copy(update={"ordinal": i, "chunk_id": cid})
        final.append(updated)

    # recompute breadcrumb_key with ordinal? already done
    return final

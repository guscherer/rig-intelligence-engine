# Fixtures de teste

PDFs reais pequenos usados pelos testes de ingestão. Sem rede.

## Atribuição

- `w3c_dummy.pdf` — "Dummy PDF file", 1 página, 13 KB.
  Fonte: W3C (https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf).
  Domínio público / uso livre para testes. Recorte: nenhum (arquivo original).

- `pdf995_vrml_excerpt.pdf` — recorte de 2 páginas (páginas 1–2) do
  "PDF 995 sample" (VRML 2.0 specification excerpt), 146 KB.
  Fonte original: Software995 (https://www.pdf995.com/samples/pdf.pdf), criado com
  Pdf995/GNU Ghostscript. Recorte feito com PyMuPDF (`Document.select([0,1])`)
  + garbage collection/deflate para caber no limite de 200 KB. Atribuição
  preservada no metadata do PDF.

Fixtures ≤ 200 KB cada. PDFs sintéticos (inclusive o "só-imagem") são
gerados dentro dos próprios testes, sem fixture binária.

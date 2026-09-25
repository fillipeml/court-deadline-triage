# Glossary

## Legal terms

| Term | Meaning |
|---|---|
| **DJEN** (Diário de Justiça Eletrônico Nacional) | The national electronic court gazette, published through the "Comunica PJe" platform. Publishing an act there is the formal way courts serve lawyers. Reading it has no procedural effect. |
| **Domicílio Judicial Eletrônico** | The electronic judicial domicile: a different platform, where opening a communication is the act of acknowledging service. Handled by the sibling project `court-notice-monitor`; its rules do not apply here. |
| **OAB** | The Brazilian bar. A lawyer's registration is a number plus a state (`12345/SP`); it is the query key of the gazette API (`bar number` in the code). |
| **Intimação** | Service of a court act on a party through its lawyer. The gazette's `tipoComunicacao` is "Intimação" for nearly every publication. |
| **Disponibilização** vs **publicação** | The day the act is made available in the gazette (`available_on`, the date the API returns) and the day it counts as published (`published_on`: the next business day, CPC art. 224, §2). |
| **Termo inicial** | The first day of the count (`start_on`): the business day after publication (CPC art. 224, §3). |
| **Data fatal** | The due date (`due_on`), the last day to perform the act. |
| **Dias úteis / dias corridos** | Business days (CPC art. 219, the default for procedural deadlines) versus calendar days (`regime` business / calendar). |
| **Recesso forense / art. 220** | The judiciary recess: deadlines are suspended from 20 December to 20 January (CPC art. 220; CLT art. 775-A). Applied in code, not in the calendar files. |
| **Expediente reduzido** | Reduced court hours (e.g. Ash Wednesday until noon at the TJGO): counts in the middle of a deadline, but cannot be its first or last day (CPC art. 224, §1). |
| **Ponto facultativo** | An optional holiday declared by the executive. Whether it extends deadlines depends on the court's act; when unstated, the engine treats the day as a business day and reports it as uncertain. |
| **Prazo em dobro** | Doubled deadline for the public treasury, the public prosecutor, the public defender and co-parties with different counsel (CPC arts. 180, 183, 186, 229). Flagged, never computed. |
| **Segredo de justiça** | A sealed case: the gazette publishes a notice instead of the body ("os arquivos da intimação não foram publicados"). |
| **Lista de distribuição** | A case-assignment list: informs which unit a new case went to; opens no deadline. |
| **Número CNJ** | The unified 20-digit case number `NNNNNNN-DD.YYYY.J.TR.OOOO`: sequence, mod-97 check digits, year, branch of the judiciary, court or region, originating unit. |
| **TJGO, TRT18, TJMG, STJ...** | Court acronyms: state courts of justice (TJ + state), regional labour courts (TRT + region), the superior court of justice, and so on. |
| **CPC / CLT** | The Code of Civil Procedure (Law 13,105/2015) and the Consolidation of Labour Laws. |
| **Contestação, Apelação, Embargos de Declaração...** | Catalogue events keep their Portuguese legal names, with an English gloss (`name_en`) next to each in `catalogue/events.json`. |
| **Juizado Especial Cível (JEC)** | Small-claims court (Law 9,099/1995). Whether its deadlines count in business or calendar days is disputed (CPC art. 219 vs FONAJE statement 165). |

## Gazette API wire names (mapped once in `djen.py`)

| Wire field | Record field |
|---|---|
| `hash` | `hash` (idempotency key) |
| `numero_processo` / `numeroprocessocommascara` | `case_number` / `case_number_masked` |
| `siglaTribunal` | `court` |
| `tipoComunicacao` / `tipoDocumento` | `communication_type` / `document_type` |
| `nomeOrgao` / `nomeClasse` | `unit` / `case_class` |
| `data_disponibilizacao` | `available_on` |
| `meio` / `link` / `ativo` / `status` | `medium` / `link` / `active` / `status` |
| `motivo_cancelamento` / `data_cancelamento` | `cancellation_reason` / `cancelled_on` |
| `texto` (HTML-escaped) | `text` (unescaped, normalised) |
| `destinatarios[].{nome, polo}` | `recipients[].{name, side}` |
| `destinatarioadvogados[].advogado.{nome, numero_oab, uf_oab}` | `lawyers[].{name, bar_number, state}` |
| query `numeroOab` + `ufOab`, `pagina`, `itensPorPagina` | `BarNumber`, page, `PAGE_SIZE` |

## Catalogue calculation modes

| Mode | Meaning |
|---|---|
| `AUTO` | model classifies, engine computes, lawyer confirms |
| `DAYS_IN_TEXT` | the number of days comes from the order; the model extracts it; not explicit, review |
| `CONDITIONAL` | a deadline exists only in a given hypothesis; review |
| `REVIEW` | body regulation, divergent case law or a different anchor; human |
| `HEARING_DATE` / `HEARING_ANCHORED` | a date set by the court, not counted from the publication |
| `NO_DEADLINE` / `NO_FATAL_DEADLINE` | internal routine, or an act admissible at any time |

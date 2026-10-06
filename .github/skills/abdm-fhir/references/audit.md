# fhir-audit

Audit an existing FHIR store's output against ABDM's NRCES profiles,
and fix the generation pipeline where it falls short. The store stays
authoritative: this skill patches what emits from it, it does not
replace it.

## 1. Collect representative output

From the integrator, get one real (or realistic test) document bundle
per record type their store produces, saved as local `.json` files.
Do not synthesize bundles yourself for this step; the point of the
audit is what the store actually emits, not what a correctly built
bundle would look like.

## 2. Tier 1 pass

Run `validate` with `kind: fhir` on each bundle, passing its `record_type`. Collect
every finding across every bundle into one gap report, grouped by
finding (the shape of the defect, for example "`Composition.author`
missing" or "`Composition.meta.profile` does not include ..."), not by
which bundle it came from. The same defect usually repeats across every
bundle the store produces, because it comes from one place in the
pipeline; grouping by bundle would make the same root cause look like
many separate problems.

## 3. Interpret with the knowledge surface

For each finding, use its Ref to read what NRCES actually demands and
why ABDM checks it. Ref names the NRCES profile the rule came from
(for example `OPConsultRecord` or `DocumentBundle`), not an atom id
directly; map it to the record type's mapping atom via `get`:
`shared.fhir.document-bundles` for envelope-level findings (Ref
`DocumentBundle`), or the type's mapping atom
(`shared.fhir.map-opconsultation`, `shared.fhir.map-prescription`,
`shared.fhir.map-diagnosticreport`, `shared.fhir.map-dischargesummary`,
`shared.fhir.map-immunizationrecord`,
`shared.fhir.map-healthdocumentrecord`, or
`shared.fhir.map-wellnessrecord`) for a Composition-element or
section-level finding. Four record types (Prescription,
DiagnosticReport, HealthDocumentRecord, ImmunizationRecord) have no
NRCES section slices: do not expect or ask for section-by-section
findings on these four, only Composition-element and entry-level ones.

Sort each finding into one of two buckets:

- **Generation-time fix.** The store already captures the data; the
  pipeline just emits the wrong shape (wrong or missing
  `meta.profile`, a malformed reference, a missing `Bundle.identifier`
  field). This is fixable in code, in this session.
- **Mapping gap.** The store never captures the data a required
  element needs at all (no encounter record to populate
  `Composition.encounter`, no coded allergy list to populate an
  `AllergyIntolerance` entry). This is not a code fix; it is a
  conversation with the integrator about what their store needs to
  start capturing, and it belongs in the gap report as an open item,
  not a silent workaround.

## 4. Patch, do not replace

For every generation-time fix, amend the integrator's existing
generation pipeline directly, or add a thin adapter that post-processes
the store's output into the compliant shape if the pipeline itself is
not reasonably editable. Either way the store keeps producing its own
output; this skill's job is the layer between that output and what
ABDM requires, not a replacement generator.

## 5. Tier 2 pass

Follow `shared.fhir.hl7-validator-recipe` against the patched output
for each record type: download the pinned `validator_cli.jar`, run it
with `-ig ndhm.in#6.5.0` (the recipe atom is the authoritative source
for the pinned version, defer to it if this ever looks stale), and
iterate the same way as tier 1, fix, re-run, until the report lists no
errors. A warning is not the same as a pass; read each one and decide
deliberately whether it is acceptable.

## 6. Done means

The gap report shows every original finding either resolved (with the
fix that resolved it) or explicitly accepted by the integrator (mapping
gaps they have chosen to defer, named as such, not silently dropped).
Tier 1 and tier 2 are both clean against every collected bundle, and
the exact commands to re-run both checks are recorded in the
integrator's repo (a make target or script) so the checks outlive this
session.

Never invent clinical codes: where the integrator's data lacks a coded
value, surface the gap to the human rather than fabricating a SNOMED
code (tier 1 will not catch a wrong code; tier 2 may not either without
a terminology server).

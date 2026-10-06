# fhir-generate

Scaffold FHIR document bundle generation for one or more ABDM record
types, directly into the integrator's own codebase, and drive it to a
clean bill of health against both validation tiers.

## 1. Establish scope

Call `search` with `kind: fhir_profile` to get the full list of ABDM record types
(the seven `hiType` values: OPConsultation, Prescription,
DiagnosticReport, DischargeSummary, ImmunizationRecord,
HealthDocumentRecord, WellnessRecord). Confirm with the integrator
which of these seven their system must produce; do not build all seven
speculatively if only one or two are needed.

Identify the language and the repository (or the path within a
monorepo) where the generation module will live. If the integrator
already has a FHIR-adjacent module (a `fhir/`, `hie-cm/`, or similar
directory), that is where this work belongs.

## 2. Learn the target shape

For each in-scope record type:

- Call `get` with `fhir:<that type>`, and once with `fhir:DocumentBundle`
  (the shared envelope profile every record type rides on top of).
- Call `get` with `fhir-example:<that type>`, to see a concrete, valid
  bundle.
- Read `shared.fhir.document-bundles` via `get` for the envelope
  rules that apply to every record type (`Bundle.type`, `Bundle.meta`,
  `Bundle.identifier`, `Bundle.timestamp`).
- Read that type's mapping atom via `get`
  (`shared.fhir.map-opconsultation`, `shared.fhir.map-prescription`,
  `shared.fhir.map-diagnosticreport`, `shared.fhir.map-dischargesummary`,
  `shared.fhir.map-immunizationrecord`,
  `shared.fhir.map-healthdocumentrecord`, or
  `shared.fhir.map-wellnessrecord`) for the Composition's required
  elements and, where NRCES defines them, its section slices.

Four record types (Prescription, DiagnosticReport, HealthDocumentRecord,
ImmunizationRecord) have no NRCES section slices: their Composition
carries one unnamed, required section whose `entry` array is what is
actually constrained. Do not scaffold section-by-section guidance for
these four; scaffold the required entry resource types their mapping
atom names instead. OPConsultation, DischargeSummary and WellnessRecord
do have named section slices; use the mapping atom's section table for
those.

## 3. Scaffold in the integrator's stack

For each in-scope record type, write a builder function that:

- Takes the integrator's own domain data as input (their patient,
  encounter, order, or report model, whatever they call it).
- Produces a document bundle matching the digest returned by
  `get` with `fhir:<type>`: the correct `meta.profile` URL on the
  Composition, every required top-level element the digest lists, and
  the section shape the mapping atom describes for that type.
- Resolves every reference internally: any resource a section entry or
  the Composition points at must be added to the bundle as its own
  entry, not left dangling.

Then write one bundle-level wrapper, shared across all in-scope
builders, that applies the `DocumentBundle` envelope constraints:
`Bundle.type` fixed to `"document"`, `Bundle.meta` and
`Bundle.meta.versionId` set, `Bundle.identifier` (`.system` and
`.value`) set, `Bundle.timestamp` set. The Composition must be the
bundle's first entry.

Follow the repository's existing conventions for module layout, error
handling, and naming. If the integrator's stack already has a FHIR
library (a typed resource model, a bundle builder), build on it rather
than duplicating it. If it has none, plain JSON construction (maps or
structs marshaled to JSON) is fine; do not introduce a new FHIR library
dependency just for this.

## 4. Iterate against tier 1

Run each builder's output bundle through `validate` with `kind: fhir`, passing the
bundle and its `record_type`. For every finding returned:

- Read the finding's Fix text.
- Apply exactly that fix to the builder (not a workaround in the test
  data).
- Re-run `validate` with `kind: fhir`.

Repeat until `validate` returns no findings for that record type,
then move to the next in-scope type.

## 5. Finish with tier 2

Tier 1 is structural and fast; it does not check nested cardinalities,
terminology bindings, or section slice discriminators. Follow
`shared.fhir.hl7-validator-recipe` end to end, in the integrator's own
environment: download the pinned `validator_cli.jar`, run it against
each builder's output bundle with `-ig ndhm.in#6.5.0` (the recipe atom
is the authoritative source for the pinned version, defer to it if
this ever looks stale), and resolve every error the report lists. A
warning is not an error; read each one and decide deliberately whether
it is acceptable, rather than treating a warning-only run as clean.

## 6. Done means

For every in-scope record type: tier 1 (`validate`, `kind: fhir`) returns no
findings, and tier 2 (the official HL7 validator) exits 0 with no
errors, against IG 6.5.0. Record the exact commands to re-run both
checks (a make target, an npm script, or a shell script committed to
the integrator's repo) so the checks outlive this session and the next
person who touches this module can re-verify without re-deriving the
commands.

Never invent clinical codes: where the integrator's data lacks a coded
value, surface the gap to the human rather than fabricating a SNOMED
code (tier 1 will not catch a wrong code; tier 2 may not either without
a terminology server).

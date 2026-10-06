# ABDM M1 integration plan (CARE)

Fresh, in-core integration of ABDM Milestone 1 (ABHA create / verify) into
`care` (backend) and `care_fe` (frontend). Built from the `abdm-m1` and
`abdm-gateway` skills in `.github/skills/`. Every request/response shape is
treated as unconfirmed until the sandbox has answered.

## Deployment interview

| Question | Answer | Effect |
|---|---|---|
| Government integrator? | Configurable | `ABDM_DEMO_AUTH_ENABLED` switches on the demographic create route |
| Mobile held at check-in? | Yes | Lookup is submitted from the phone number CARE already carries (`?phone_number=`) |
| Callback ABDM can reach? | No / unsure | Scan-and-register is out of scope; M1 identifier journeys only |
| Fingerprint / iris reader? | No | No biometric routes |
| Patients arrive with the ABHA app? | Yes | Face auth as a secondary method (`ABDM_FACE_AUTH_ENABLED`) |
| Counter style | Combined | One "Find or create ABHA" entry, lookup first, ABDM's answer picks login vs create |
| ABHA required? | No | ABHA step has a "Not now" exit; registration always completes |
| Extra placements | Card & QR | ABHA card / QR on the patient page. Find-forgotten, update-mobile: not now |

## Survey inventory

| Find | Answer |
|---|---|
| Languages / runtimes | Python 3.13, Django 6 (`Pipfile`); React 19 + TS + Vite (`care_fe/package.json`) |
| Build / run / test | `python manage.py test care.abdm --keepdb`; `ruff check`; FE `npx tsc --noEmit` |
| FE/BE split | FE calls `/api/v1/*` via `care_fe/src/Utils/request/{query,mutate}.ts`; every ABDM call goes through the backend |
| Outbound HTTP client | `requests` (no shared wrapper). New: `care/abdm/client.py` |
| Secrets / config | `environ.Env` in `config/settings/base.py`; `.envrc` exports `ABDM_*` locally |
| Cache | Redis via Django cache (`config/settings/base.py`) |
| Patient identifiers | `PatientIdentifierConfig` (instance-level, keyed by `config.system`) + `PatientIdentifier` rows — `care/emr/models/patient.py`. ABHA number and address become two instance identifier configs, not a new table |
| Visit / encounter (for M2) | `care/emr/models/encounter.py` (`Encounter`) |
| Inbound routing / auth | `config/api_router.py` (DRF router, JWT auth); no public callback needed for M1 |
| Crypto helpers | none; `cryptography` (already in `Pipfile.lock`) for RSA-OAEP. New: `care/abdm/crypto.py` |
| Permissions | `AuthorizationController.call("can_create_patient", user)` (`care/security/permissions/patient.py`) |
| Errors / logging | DRF `ValidationError` / `emr_exception_handler`; FE Sonner toasts (`care_fe/src/Utils/request/errorHandler.ts`). Never log tokens, Aadhaar, mobile, OTP |

## Touchpoints

Backend, new app `care/abdm/` (added to `LOCAL_APPS`):

| Concern | File |
|---|---|
| Settings (`ABDM_ENABLED`, URLs, client id/secret, CM id, method toggles, identifier systems) | `config/settings/base.py` (new block) |
| Gateway session token, cached until shortly before `expiresIn` | `care/abdm/client.py` (new) |
| ABHA HTTP client: `REQUEST-ID` (logged), UTC `TIMESTAMP`, error parsing tolerant of `ABDM-xxxx: ` and empty bodies | `care/abdm/client.py` (new) |
| Certificate cache with validity window; encrypt with the algorithm the certificate names, refuse unknown ones | `care/abdm/crypto.py` (new) |
| Server-side journey state (txnId, T/X/refresh tokens) in cache, bound to the requesting user; FE only sees an opaque journey id | `care/abdm/journey.py` (new) |
| API (`/api/v1/abdm/abha/...`) | `care/abdm/api/viewsets/abha.py` (new), registered in `config/api_router.py` |
| Profile → CARE patient facts mapping | `care/abdm/profile.py` (new) |
| Identifier configs for ABHA number / address | `care/abdm/management/commands/setup_abdm_identifiers.py` (new) |
| Tests (mocked HTTP) | `care/abdm/tests/` (new) |

Frontend (`care_fe`):

| Concern | File |
|---|---|
| Types + routes | `src/types/abdm/abha.ts`, `src/types/abdm/abhaApi.ts` (new) |
| Fact store (write-once + provenance) | `src/components/Abdm/useAbhaFacts.ts` (new) |
| ABHA step (identify → OTP → choose account → choose address → fill form) | `src/components/Abdm/AbhaRegistrationStep.tsx` (new), rendered above "Patient basics" in `src/components/Patient/PatientRegistration.tsx` for new patients when the backend reports ABDM enabled |
| ABHA card & QR on patient page | `src/components/Abdm/AbhaCardDialog.tsx` (new), placed on the patient home/details page |
| i18n | `public/locale/en.json` |

## Journeys, in build order

1. **Gateway session + certificate** — exit: token issued, certificate returns `publicKey` + `encryptionAlgorithm`. *Observed 2026-10-05 against sandbox: 200/200, `RSA/ECB/OAEPWithSHA-1AndMGF1Padding`.*
2. **Lookup / login** (mobile → `abha/search` free lookup + OTP by index; ABHA number → OTP; Aadhaar → login OTP). Only `ABDM-1114` means "no ABHA". Branch on `refreshToken`, not on `accounts.length`; mobile path exchanges the T-token at `login/verify/user`. Exit: verified login returns accounts, profile readable with X-token. *Observed 2026-10-05: unheld ABHA number refused `404 ABDM-1114` before any OTP, through `care.abdm` client + encryption. OTP verification still needs a sandbox test identity.*
3. **Create by Aadhaar OTP** → mobile verify when needed → address suggestions → address create. Exit: `healthIdNumber` + `preferredAbhaAddress` returned.
4. **Create by demographic auth** (behind `ABDM_DEMO_AUTH_ENABLED`). Exit: `kycVerified: true`, `new` flag.
5. **Face auth** create/login (behind `ABDM_FACE_AUTH_ENABLED`). Exit: `capturePID` status resolves and verify returns accounts.
6. **Card & QR** on patient page. Refresh token cached per ABHA number (TTL = `refreshExpiresIn`); when absent, re-verify by OTP. Exit: card image renders for a linked patient.

Each journey's backend exit condition is covered by tests in `care/abdm/tests/` (mocked) and then observed once against the sandbox.

## Rules carried into code

- Lookup before create, for every identifier. Creation only from Aadhaar.
- Registration completes without an ABHA; ABHA identifier fields stay optional.
- Profile fills the form; the desk confirms. Corrections never write back to ABDM.
- Fresh `REQUEST-ID` per call, logged; sensitive values never logged.
- Account chooser whenever a verification returns more than one account.

# M2: CARE as HIP

## Deployment answers

| Question | Answer |
|---|---|
| HIP mapping | Per facility: `AbdmFacility.hip_id`, set at Facility settings → ABDM |
| Callback | Bridge URL `https://<tunnel host>/abdm`; Django serves `/abdm/api/v3/<callback>` (`config/urls.py`) |
| Record types | OPConsultation, Prescription (`care/abdm/fhir.py`) |
| When to link | Automatically, when a medication request, condition, allergy or service request is saved on an encounter (`care/abdm/signals.py`, debounced) |
| Discovery matching | Verified ABHA number / address only; never demographics |
| Integrator panel | Admin → ABDM Exchanges |

## Touchpoints

| Concern | File |
|---|---|
| Exchange log, care contexts, link tokens, consents, HI requests | `care/abdm/models.py` |
| Gateway calls recorded before sending (waiter registered first) | `care/abdm/gateway.py` |
| HIP-initiated linking: token → link → notify on later changes | `care/abdm/linking.py`, `care/abdm/tasks.py` |
| Inbound callbacks: bearer present, served HIP, answers a sent request; fail closed | `care/abdm/api/callbacks.py` |
| Fidelius ECDH (curve25519 Weierstrass via X25519 + mapping), HKDF-SHA256, AES-256-GCM | `care/abdm/fidelius.py` |
| NRCES bundles | `care/abdm/fhir.py` |
| Facility HIP ID + readiness, encounter link status + retry, exchange log | `care/abdm/api/viewsets/hip.py`; FE `src/pages/Facility/settings/abdm/`, `src/components/Abdm/AbdmCareContextStatus.tsx`, `src/pages/Admin/Abdm/` |

## Exit conditions

- Bridge `PATCH` accepted (202) and read back. *Observed 2026-10-05.*
- Unauthenticated callback through the public bridge refused `401` before any handling. *Observed 2026-10-05.*
- Link token for an unknown address: `400 ABDM-9999`, retry `400 ABDM-1092`; both parsed and the second points at the first. *Observed 2026-10-05.*
- Bundles: tier 1 (`validate`, kind fhir) clean for both record types. Re-run: `ABDM_DUMP_BUNDLES=/tmp/b python manage.py test care.abdm.tests.test_fhir` then validate the dumped files. Tier 2 (HL7 `validator_cli.jar`, `-ig ndhm.in#6.5.0`) pending: needs a Java runtime.
- Encryption: an independent Weierstrass HIU decrypts our payload (`care/abdm/tests/test_fidelius.py`).
- Pending sandbox identity: token → link → `on_carecontext`; discovery/init/confirm from the PHR app; consent → data push.

# M3: CARE as HIU

## Deployment answers

| Question | Answer |
|---|---|
| HIU ID | The facility's HIP ID (`AbdmFacility.hip_id`); readiness checks it carries the `HIU` type on the bridge |
| Who requests | Users who can write to the patient record, on behalf of a facility they belong to |
| After grant | Automatic: every artefact the grant returns is fetched, then its records requested |
| Received records | View-only in the patient's ABDM tab; erased at the artefact's `dataEraseAt` (hourly beat task) and on revocation/expiry |
| Data push URL | `ABDM_CALLBACK_BASE_URL` + `/abdm/data-push/<single-use token>/` (`config/urls.py`) |

## Touchpoints

| Concern | File |
|---|---|
| Consent requests, artefacts (one per HIP), received records | `care/abdm/models.py` (`AbdmHiu*`) |
| Init → on-init → notify → fetch → HI request → push → notify; status; erase | `care/abdm/hiu.py`, tasks in `care/abdm/tasks.py` |
| HIU key pair kept until the push; decrypt with the sender's key material | `care/abdm/fidelius.py` (`Decryptor`) |
| HIU callbacks and the data push endpoint | `care/abdm/api/callbacks.py` |
| Raise / refresh / fetch again; patient overview + received records | `care/abdm/api/viewsets/hiu.py`, `care/abdm/api/viewsets/hip.py` |
| Request form, request list, received records | FE `src/components/Abdm/AbdmConsentRequest*.tsx`, `AbdmReceivedSheet.tsx`, ABDM patient tab |

## Exit conditions

- Init accepted (202) and answered on `hiu/consent/request/on-init` with a consent request id. *Observed 2026-10-05.*
- Status accepted (202) and answered on `hiu/consent/request/on-status` (`REQUESTED`). *Observed 2026-10-05; the synchronous 200 form is also handled.*
- Grant → every artefact fetched → HI request → push decrypted → `RECEIVED` notify; revocation erases. Covered by `care/abdm/tests/test_m3.py`. *Pending on the sandbox: needs the patient to approve in a PHR app.*

# M4: Facility and professional registries (HFR, HPR)

## Deployment answers

| Question | Answer |
|---|---|
| Facility journeys | Find in HFR and use the ID as the HIP ID; serve it from this bridge (HIP + HIU); onboard a new facility into HFR |
| Professional journeys | Link a CARE user to an existing HPR ID; create an HPR ID (Aadhaar on ABDM's page); registering professional details is **not built** (below) |
| Who manages | Facility admins (`can_update_facility_obj`); targets are the facility's members, or the admin themself |
| HPR proof | The professional signs in to HPR with an Aadhaar OTP; a new HPR ID is proven by the Aadhaar verification that created it |
| Registry host | `ABDM_REGISTRY_URL` (sandbox default); same bearer as the gateway session |

## Touchpoints

| Concern | File |
|---|---|
| Registry calls (HFR search/masters/onboard, bridge services, HPR auth/creation) | `care/abdm/registry.py`, `client.registry_request` |
| HIS errors: the cause is in `details[]` under a generic `HIS-422` | `client._find_error` |
| HPR link per user; HFR application (tracking ID kept across refusals) | `care/abdm/models.py` (`AbdmProfessional`, `AbdmHfrApplication`) |
| Facility-scoped API | `care/abdm/api/viewsets/registry.py` (`abdm/registry/<facility>/…`) |
| HPR ID number in shared records and consent requests | `fhir.practitioner_reference`, `hiu._requester` (`ABDM_HPR_IDENTIFIER_SYSTEM`) |
| Settings UI | FE `src/pages/Facility/settings/abdm/` (`AbdmSettings`, `AbdmHfr*Sheet`, `AbdmHpr*Sheet`, `AbdmProfessionalsCard`) |

## Rules learned on the sandbox

- HFR search refuses `resultsPerPage` below 10 (HIS-4047) and needs state + ownership without an ID.
- HFR master codes come padded with trailing spaces; trim them.
- HPR categories need `role` (0 = professionals); without it HPR answers "Role is not valid".
- The HPR certificate (`/api/v1/auth/cert`) is a bare PEM RSA key; the creation-flow mobile OTP is sent encrypted with it. The login OTP goes plain, as the published sample shows.
- The HPR token of the signed-in professional is the `x-hprid-auth` header for HFR basic-information and submit; it is kept server-side, per user, and only for the user who signed in themself.

## Exit conditions

- HFR lookup by ID and by name/state/ownership, LGD states/districts/sub-districts, every master list, HPR categories, HPR certificate. *Observed 2026-10-05.*
- Unknown HPR ID surfaces `HIS-3008 Invalid HPID.`; HPR login for an unknown ID surfaces `HIS-1001`. *Observed 2026-10-05.*
- Bridge registration (`MutipleHRPAddUpdateServices`), HPR login with a real professional, HPR ID creation, HFR submission: covered by `care/abdm/tests/test_m4.py`. *Pending on the sandbox: needs a real professional's Aadhaar OTP; bridge registration is a write to the shared bridge, left to the admin's button.*
- Not built: `register-professional-new`. Its body sections (`personalInformation`, `registrationAcademic`, …) are published as bare objects with no fields, and the sandbox answers an empty body with a bare HIS-500. Build it once ABDM publishes the field shapes.

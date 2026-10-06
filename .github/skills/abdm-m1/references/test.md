# HIE-CM m1 test

Walks the ABDM M1 functional test cases, ABHA creation and verification, against the system you built and the sandbox. Each case ends in one of four recorded outcomes, never in an opinion.

## What this skill does

- Runs every M1 test case in the ABHA creation and verification set against your system and the sandbox, one case at a time
- Records, for each case, the sandbox response and REQUEST-ID that prove it, or the screen that has to be attested, or the human step it stopped at
- Writes a manifest of case ids to request ids at the end, which is the evidence a reviewer checks against the gateway rather than a folder of screenshots

## What it needs from you

| Need | Where it comes from |
|---|---|
| Sandbox client id and secret | The ABDM sandbox portal, under your registered application |
| Your system running against the sandbox hosts | Your deployment or a local build. The skill drives your system, not the sandbox directly |
| A way to trigger each journey in your system | A screen, an API or a script. Say which at the start |
| A person with an Aadhaar linked mobile, for OTP cases | Present at the desk for the run. Every OTP is a human step and the skill stops for it |
| A fingerprint or face device, for the biometric cases | Only if you claim those cases. Without one they are recorded as not run |
| Whether you are a government or a private integrator | The set marks some cases mandatory for one and optional for the other |

## Say one of these

- "Walk the M1 test cases against my sandbox and log each one."
- "Run only the ABHA verification cases, VRFY_ABHA_101 to 405."
- "Re-run CRT_ABHA_112, the address suggestion case failed yesterday."
- "Write a terminal script that runs the M1 test cases and asks me for the Aadhaar number and each OTP."

## What happens first

One question: which cases. All of them, one function group, or a list of ids. Then the preconditions for the first case are checked before anything is sent. Nothing else is asked until a case needs a human.

## How this skill runs

Every case is an observe, orient, decide, act loop. Observe the live state: the last response, the last REQUEST-ID, what your screen shows. Orient against the case below. Decide the cheapest action that produces a new observation. Act, paste the raw result, return to observe. A case is done only when its exit condition is observed, never because the step should have worked.

Loop limit: 3 passes per test case. Hitting the limit is an escalation: state what was observed with request ids, what was tried, name one section of this skill or one operation page to read, and ask one question.

### The four outcomes

| Outcome | Record it when | Never when |
|---|---|---|
| `passed` | The exit condition is observed and the observation is pasted verbatim | The response was not pasted. A pass with no output is a fail |
| `failed` | Three passes and the exit condition was not observed, or the sandbox returned the refusal the case expects you to handle and your system did not handle it | A human step was missing. That is `needs-human` |
| `needs-human` | The case reached an OTP, a biometric scan, an operator's document check, or a person who was not there | Ever as a substitute for a fail you can see |
| `not-run` | The case does not apply to your entity, you do not claim the optional capability, or ABDM publishes no operation for it | To skip a mandatory case that applies to you |

### The three kinds of evidence

Every case names one of these. It decides what the manifest carries.

- **sandbox.** A call the gateway sees. Evidence is the HTTP status, the body and the REQUEST-ID, pasted. The exit condition is a literal in the body. A reviewer can check this against the gateway's own record, which is why it outranks the other two.
- **screen.** A rule about what your system shows or stores, which no call proves. Evidence is one screenshot or a short recording and the design rule it satisfies. A screen case is attested, not observed, and the manifest marks it so.
- **human.** A step only a person can do. Evidence is the observation just before it and the outcome `needs-human` when nobody was there.

### Rules that hold for every case

- Search before create. Every identifier goes to the login path first, and only ABDM-1114 on the verify says nobody holds an account. Creating on any other answer gives the patient two numbers, which nothing merges. `hiecm.concept.m1-avoiding-duplicate-abha`
- Never ask twice. A value the transaction already holds, the Aadhaar number, the mobile, the txnId, is carried, not re-entered. `hiecm.concept.m1-never-ask-twice`
- Two tokens. The gateway access token goes in `Authorization`. The user token an enrolment or a login returns goes in `X-token`. Profile calls need both.
- Fresh `REQUEST-ID` on every call, logged before sending. A reused id is refused, and after a failure the id is the only handle on the call.
- Paste the response. A step with no pasted output is not done.
- Sensitive values travel encrypted: Aadhaar, mobile, email, OTP. Read the algorithm from the certificate call rather than hard coding a padding.
- One question when you escalate. The person is being interrupted.

### The run record

Append one block per loop pass. It is the raw material for the manifest.

```text
case: CRT_ABHA_101   pass: 1 of 3   at: 2026-09-29T10:14:02Z
observed: POST /abha/api/v3/enrollment/enrol/byAadhaar  REQUEST-ID 6f1c...  HTTP 200
body: {"message":"Account created successfully","txnId":"...","tokens":{"token":"<X-token>",...},"ABHAProfile":{"ABHANumber":"91-...",...}}
matched: exit condition for CRT_ABHA_101, step 2
next: CRT_ABHA_113
```

### When the run is a script

Asked for a test script, a test command or automated tests, build one interactive terminal runner that walks the cases below. It does the typing. Every rule above still holds.

| Rule | Why |
|---|---|
| Name every check by its case id from this skill, such as `CRT_ABHA_101`. Never invent a numbering such as `TC01` | The functional testing report quotes these ids. A check with no case id answers nothing a reviewer asks |
| At each `human` step, stop and prompt in the terminal for the value: Aadhaar number, mobile, OTP, the chosen address. Read it from stdin, encrypt it, send it | Every M1 success path passes through an OTP. A runner that never asks never reaches one |
| Never write a typed value to disk, a log or the manifest, and never hard code one | An Aadhaar number and an OTP belong to the person, not the run |
| Run each `sandbox` case's success path and the refusal its exit condition names, as separate checks | The case passes only when both are observed |
| Compare the status and the body literal the exit condition names, such as `200` with `tokens.token` present, or `422` with `error.code` `ABDM-1204` | A status alone never passes a check |
| A `4xx` passes only where the case's exit condition names that refusal | A `400` on a success path step is `failed` |
| A blank answer at a prompt records the case `needs-human` and moves to the next case | Nobody present is neither a pass nor a fail |
| A `screen` case prints its check, then asks `passed? y/n` and the evidence file name | No call proves a screen, so the case is attested |
| At the end, print one line per case id with its outcome and request ids, then write the manifest in the last section | The person reads outcomes by case id, not by script step |

A run reads like this. The person's values are typed at the prompts and never echoed back.

```text
CRT_ABHA_105  POST /v3/enrollment/request/otp  REQUEST-ID 3b9e...  HTTP 200  txnId present  matched
  Enter the OTP sent to the mobile ending 1234, or leave blank if nobody is here:
CRT_ABHA_107  wrong OTP  REQUEST-ID 7c02...  HTTP 422  error.code ABDM-1204  matched
CRT_ABHA_107  right OTP  REQUEST-ID 9a41...  HTTP 200  tokens.token present  matched
CRT_ABHA_107  passed
```

Nudge: calls with a bad `scope`, a bad `loginHint` or a made up `txnId` test your client, not a case. Run them first if you want them, label them `preflight`, and keep them out of the case counts.

## Test cases

The ids, the mandatory marks and the wording of each check are ABDM's, from the M1 ABHA creation and verification set. The sections are grouped as the set groups them. Where the set names an operation, the operation id here is the one in `references/integrate.md`, which carries the host, the headers and a full request.

### CRT_ABHA_101 to 115: create an ABHA by Aadhaar OTP

Applies to every integrator. Mandatory unless marked. This is the group every other creation group repeats with a different authentication step, so it is written in full and the others state only what differs.

Loop limit: 3 passes per test case.

**Preconditions.** A gateway access token less than 30 minutes old. A person present with an Aadhaar linked mobile. Their Aadhaar number searched first on the login path and not found, so the run creates rather than duplicates.

#### CRT_ABHA_101, the option exists. `sandbox`

Your system offers ABHA creation by Aadhaar OTP, and the journey completes. Drive it end to end through your screen or API.

Calls, in order: `m1_post_v3_enrollment_request_otp_aadhaar_otp`, `m1_post_v3_enrollment_enrol_byaadhaar_otp`, the optional mobile and email verifications, `m1_get_v3_enrollment_enrol_suggestion_create_abha_aadhaar_otp`, `m1_post_v3_enrollment_enrol_abha_address_create_abha_aadhaar_otp`, then `m1_get_v3_profile_account` and `m1_get_v3_profile_account_abha_card`.

Exit condition: three literals, all pasted.

1. `m1_post_v3_enrollment_enrol_byaadhaar_otp` returns 200 with `tokens.token` present and `ABHAProfile.ABHANumber` present.
2. `m1_post_v3_enrollment_enrol_abha_address_create_abha_aadhaar_otp` returns 200 with `healthIdNumber` and `preferredAbhaAddress`.
3. `m1_get_v3_profile_account`, sent with that `X-token`, returns 200 with the same `ABHANumber`.

Nudge: read `message` on step 1. `Account created successfully` is a new account. `This account already exist` is a 200 too, and it means the search-first rule was skipped or the sandbox person already holds one. Record which, because the second is a screen failure on CRT_ABHA_101 even though the API passed.

#### CRT_ABHA_102, consent is shown and recorded. `screen`

Your system shows the published ABDM consent text before the Aadhaar number is asked for, and stores that the person agreed, with when. Evidence: the consent screen, and the stored record for this run. `hiecm.concept.m1-screen-contract`

#### CRT_ABHA_103, consent in another language. `screen`, optional

The same consent offered in at least one language other than English. Evidence: the screen in that language. Record `not-run` if you do not claim it.

#### CRT_ABHA_104, an invalid Aadhaar number is refused before any call. `screen`

Enter an 11 digit and a 13 digit value. Your system refuses each with a message that says the number is not valid, and sends nothing. Evidence: the refusal on screen and an empty call log for that attempt. Your own check has to be the strict one here; the sandbox's refusal for a bad number is not the one this case is about. `hiecm.concept.m1-honest-screen-states`

#### CRT_ABHA_105, the Aadhaar OTP is requested and can be entered. `sandbox`, then `human`

Exit condition: `m1_post_v3_enrollment_request_otp_aadhaar_otp` returns 200 with a `txnId` and a `message` that names the masked mobile. Paste it. Then stop: the OTP arrives on the person's phone and only they enter it. If they are not there, record `needs-human` and the txnId, and do not mark the case passed or failed.

Screen check alongside: the prompt tells the person the OTP went to the mobile linked with Aadhaar and shows the last digits, which the `message` carries.

#### CRT_ABHA_106, resend OTP. `screen`

The resend control is disabled for 60 seconds after each send and works at most twice. Evidence: a recording or three timestamped screenshots: disabled at send, enabled after 60 seconds, disabled after the second resend. A resend that works reuses the `txnId`; a fresh `txnId` is a new request, not a resend.

#### CRT_ABHA_107, the OTP is verified, and a wrong OTP is refused. `sandbox`, `human`

Two observations, both needed.

1. A wrong OTP: `m1_post_v3_enrollment_enrol_byaadhaar_otp` returns 422 with `error.code` `ABDM-1204` and a message naming an invalid Aadhaar OTP value, and your screen says the OTP was wrong and lets the person retry without re-entering the Aadhaar number.
2. The right OTP: the 200 from CRT_ABHA_101 step 1.

The person enters both OTPs. Stop for each.

#### CRT_ABHA_108, the communication mobile is the Aadhaar mobile. `sandbox`, optional

If your system checks whether the mobile the person gave is the Aadhaar linked one and skips the second OTP when it is, drive that path. Exit condition: the journey reaches the ABHA address step with no `mobile-verify` call in the log. Record `not-run` if you always verify, which CRT_ABHA_109 then covers.

#### CRT_ABHA_109, a different communication mobile is verified. `sandbox`, `human`

Give a mobile that is not the Aadhaar linked one. Exit condition: `m1_post_v3_enrollment_request_otp_mobile_verify_create_ab_1b66bb` returns 200 with a `txnId`, the person enters the OTP, and `m1_post_v3_enrollment_auth_byabdm_mobile_verify_create_ab_091285` returns 200. A wrong OTP here is refused on screen and the person can retry.

#### CRT_ABHA_112, the ABHA address is suggested and validated. `sandbox` and `screen`

Mandatory for private and government integrators. Optional for a programme that creates a default address by demographic authentication.

Exit condition: `m1_get_v3_enrollment_enrol_suggestion_create_abha_aadhaar_otp` returns 200 with `abhaAddressList` holding at least three entries, and `m1_post_v3_enrollment_enrol_abha_address_create_abha_aadhaar_otp` returns 200 with `preferredAbhaAddress` equal to the one chosen.

Screen check: at least three suggestions are shown, or a free field with these rules printed beside it, and an address already taken is refused with a message that says so and offers the suggestions.

```text
length 8 to 18
letters, digits, or both
at most one dot and at most one underscore, neither first nor last
```

#### CRT_ABHA_113, the ABHA number is displayed. `screen`

The 14 digit ABHA number and the ABHA address from CRT_ABHA_112 are shown together after creation. Evidence: the screen, with the number matching `healthIdNumber` from the pasted response.

#### CRT_ABHA_114, the ABHA card can be viewed and downloaded. `sandbox` and `screen`

Mandatory for private integrators that generate the card. Exit condition: `m1_get_v3_profile_account_abha_card` returns 200 with content type `image/png`, sent with the `X-token` from creation. Screen check: the card shown carries the ABHA number, the QR code, date of birth, gender and the ABHA address. The photo is optional.

#### CRT_ABHA_115, your own card carries the ABHA details. `screen`

For an integrator that prints its own programme card instead. Mandatory for government where CRT_ABHA_114 is not done. The card shows the ABHA number and address, and your system stores both against your own patient id. Evidence: the card and the stored record.

### CRT_ABHA_201 to 210: create an ABHA by Aadhaar biometric

Applies to every integrator. Optional, except that CRT_ABHA_209 is mandatory for a private integrator that generates the card and one of 209 or 210 is mandatory for government.

Loop limit: 3 passes per test case.

Same cases as 101 to 115 with these differences. Run each as its counterpart above and record the counterpart's evidence.

| Case | Counterpart | What differs |
|---|---|---|
| CRT_ABHA_201 | 101 | The creation call is `m1_post_v3_enrollment_enrol_byaadhaar_fingerprint` or `m1_post_v3_enrollment_enrol_byaadhaar_face`. Exit condition is the same 200 with `tokens.token` and `ABHAProfile.ABHANumber` |
| CRT_ABHA_205 | 105 and 107 | `human`: the person scans. A failed scan is refused on screen and can be retried. Face runs `m1_post_v3_enrollment_enrol_auth_init_create_abha_face_au_4dea33` then the capture call first |
| CRT_ABHA_206, 207 | 108, 109 | Unchanged |
| CRT_ABHA_208 | 113 | Unchanged |
| CRT_ABHA_209, 210 | 114, 115 | Unchanged |
| CRT_ABHA_202, 203, 204 | 102, 103, 104 | Unchanged |

Without a registered device the whole group is `not-run`, with that reason.

### CRT_ABHA_301 to 309: create an ABHA by demographic authentication

Government entities only. Mandatory for them. A private integrator records the group `not-run`.

Loop limit: 3 passes per test case.

#### CRT_ABHA_301 and 305, the demographic call creates the account. `sandbox`

One call, `m1_post_v3_enrollment_enrol_byaadhaar_demo_auth_create_ab_81107d`, with the name, date of birth, gender, Aadhaar number, mobile, address, state and district as they read on the Aadhaar card. Exit condition: 200 with `healthIdNumber`, `healthId` and `kycVerified` `true`.

Then the mismatch: send the same call with the date of birth changed. Exit condition: a 422 whose message says the information does not match the details on record with Aadhaar, and your screen says so without creating anything. Both observations, both pasted.

Nudge: the same mobile on a seventh account is refused with ABDM-1124. That is a mobile limit, not a demographic mismatch. Read `error.message`.

#### CRT_ABHA_305 address, the three cases. `sandbox` and `screen`

The address on the card and the profile is the same one in all three cases: the existing address when the person had one, the address they chose when they chose one, and the default `<ABHA number>@sbx` when neither. Evidence: `healthId` in the creation response and the address on `m1_get_v3_profile_account`, equal, for whichever case the run hit. Record which.

#### CRT_ABHA_306, the profile is filled from the response, not typed. `screen`

Name, date of birth and gender are shown filled and not editable. Address, mobile and email are editable. Evidence: the form after creation. `hiecm.concept.m1-confirm-the-filled-form`

#### CRT_ABHA_302, 303, 304, 307, 308, 309

As 102, 103, 104, 113, 114 and 115.

### CRT_ABHA_401 to 411: create an ABHA by driving licence or PAN

ABDM's M1 specification publishes no enrolment by document operation. Record every case in this group `not-run` with that reason, whatever your entity type, until an operation is published. Do not improvise a call.

### VRFY_ABHA_101 and 102: verify an ABHA number or address by Aadhaar OTP

Applies to every integrator. Mandatory.

Loop limit: 3 passes per test case.

**Preconditions.** A person present with an ABHA and the Aadhaar linked mobile.

#### VRFY_ABHA_101, by ABHA number. `sandbox`, `human`

Calls: `m1_post_v3_profile_login_request_otp_abha_number_aadhaar_otp`, the OTP, `m1_post_v3_profile_login_verify_abha_number_aadhaar_otp`, then `m1_get_v3_profile_account` with the returned token as `X-token`.

Exit condition: the verify returns 200 with `authResult` `success` and `accounts[0].ABHANumber`, and the profile call returns 200 with the same `ABHANumber`. A wrong OTP returns 400 with `otpValue` naming an invalid OTP value, and your screen says the verification failed.

Screen checks alongside: resend as in CRT_ABHA_106; name, date of birth and gender shown not editable; the profile stored against your own patient id after verification.

Nudge: the accounts array already carries the whole registration form. Fill the form from it before the profile call, so the person reads back rather than types.

#### VRFY_ABHA_102, by ABHA address. `sandbox`, `human`

Calls: `m1_post_v3_phr_web_login_abha_search_abha_address_login_a_de8184`, `m1_post_v3_phr_web_login_abha_request_otp_aadhaar_otp`, the OTP, `m1_post_v3_phr_web_login_abha_verify_aadhaar_otp`, then `m1_get_v3_phr_web_login_profile_abha_profile_abha_address_c04e83`.

Exit condition: the verify returns 200 with a token, and the profile call returns 200 carrying the ABHA number and the address searched for. Paste both.

### VRFY_ABHA_201 and 202: verify by the ABHA linked mobile OTP

Mandatory. As VRFY_ABHA_101 and 102 with the mobile OTP operations: `m1_post_v3_profile_login_request_otp_abha_number_abha_otp` and `m1_post_v3_profile_login_verify_abha_number_abha_otp` for the number, `m1_post_v3_phr_web_login_abha_request_otp_mobile_otp` and `m1_post_v3_phr_web_login_abha_verify_mobile_otp` for the address. Same exit conditions, same screen checks.

Loop limit: 3 passes per test case.

### VRFY_ABHA_301 to 305: fetch ABHA details by the communication mobile

Mandatory. This is the lookup that costs no Aadhaar OTP, so it is the one your desk should run first.

Loop limit: 3 passes per test case.

#### VRFY_ABHA_301, an invalid mobile is refused. `screen`

A nine digit and an eleven digit value are refused on screen with a message asking for a valid mobile, and nothing is sent.

#### VRFY_ABHA_302, no ABHA on this mobile. `sandbox`, `human`

Calls: `m1_post_v3_profile_login_request_otp_mobile`, the OTP, `m1_post_v3_profile_login_verify_mobile_otp`.

Exit condition: the verify returns 404 with `error.code` `ABDM-1114`. Your screen says no ABHA number is linked to this mobile, and offers to create one. The create offer is the point of the case; a dead end fails it. `hiecm.concept.m1-journey-completes-without-abha`

#### VRFY_ABHA_303, one or more ABHAs on this mobile. `sandbox`, `human`

Same two calls with a mobile that holds accounts, then `m1_post_v3_profile_login_verify_user` with the chosen `ABHANumber` and the first verify's token as `T-token`, then `m1_get_v3_profile_account`.

Exit condition: the first verify returns 200 with `accounts` holding at least one entry with `ABHANumber`, `preferredAbhaAddress`, `name` and `profilePhoto`; the user verify returns 200 with `token`; the profile call returns 200 with the chosen `ABHANumber`.

Screen checks: every account in the array is listed with name, number, address and photo; choosing one already linked to a patient in your system says so and names your patient id; choosing one not yet linked registers and links it. `hiecm.concept.m1-two-routes-to-the-profile`

Nudge: read the array as plural. One mobile can hold up to six accounts, and a screen that shows the first one silently links the wrong person.

#### VRFY_ABHA_304, a wrong OTP. `sandbox`, `human`

Exit condition: `m1_post_v3_profile_login_verify_mobile_otp` returns 400 with `otpValue` naming an invalid OTP value, and your screen says so and allows a retry without re-entering the mobile.

#### VRFY_ABHA_305, resend. `screen`

As CRT_ABHA_106.

### VRFY_ABHA_401 to 405: fetch ABHA details by Aadhaar number

Mandatory.

Loop limit: 3 passes per test case.

#### VRFY_ABHA_401, an invalid Aadhaar is refused. `screen`

As CRT_ABHA_104, on the verification screen.

#### VRFY_ABHA_403, no ABHA on this Aadhaar. `sandbox`, `human`

Calls: `m1_post_v3_profile_login_request_otp_aadhaar`, the OTP, `m1_post_v3_profile_login_verify_aadhaar_otp`.

Exit condition: the request returns 200 with a `message` naming the masked Aadhaar mobile, the person enters the OTP, and the verify returns 404 with `error.code` `ABDM-1114` and a message that no ABHA user is registered with this Aadhaar number. Your screen says so and offers creation, and the creation path does not ask for the Aadhaar number again. `hiecm.concept.m1-never-ask-twice`

#### VRFY_ABHA_404, an ABHA exists on this Aadhaar. `sandbox`, `human`

Same calls with an Aadhaar that holds an account, then `m1_get_v3_profile_account`.

Exit condition: the verify returns 200 with `authResult` `success` and `accounts[0].ABHANumber`; the profile call returns 200 with the same number. Screen checks: the profile is shown, the card can be downloaded as in CRT_ABHA_114, and the account is registered and linked to your patient id if it was not already.

#### VRFY_ABHA_402 and 405

A wrong OTP and resend, as VRFY_ABHA_304 and 305.

### VRFY_ABHA_501 and 502: verify by fingerprint, government entities

Optional. `human`. Calls: `m1_post_v3_1_profile_login_verify_fingerprint` for a number. The set names no operation for an address by fingerprint; record VRFY_ABHA_502 `not-run` with that reason. Exit condition for 501: 200 with `accounts[0].ABHANumber`, then the profile call as VRFY_ABHA_101. Without a device, `not-run`.

Loop limit: 3 passes per test case.

### Reading the ABHA QR code, optional

The set numbers this row VRFY_ABHA_501 as well. Record it as `QR-read` so the two are told apart in the manifest.

`screen`. No call. Your system scans a person's ABHA QR code and fills name, date of birth, gender and mobile into registration from it. Evidence: the filled form after a scan, with nothing typed. `hiecm.concept.m1-two-routes-to-the-profile`

Loop limit: 3 passes per test case.

### PROF_ABHA_601 to 605: profile update

Optional. Each is `sandbox` and `human`, since every change is confirmed by an OTP.

Loop limit: 3 passes per test case.

| Case | Calls | Exit condition |
|---|---|---|
| PROF_ABHA_601, mobile | `m1_post_v3_profile_account_request_otp_update_mobile`, the OTP, `m1_post_v3_profile_account_verify_update_mobile` | The verify returns 200 with `authResult` `success` and a message that the mobile number was linked; `m1_get_v3_profile_account` then shows the new masked `mobile` |
| PROF_ABHA_602, photo | `m1_patch_v3_profile_account_profile_photo` | 200, and `m1_get_v3_profile_account` returns the new `profilePhoto` |
| PROF_ABHA_603, email | The request and verify calls above with the email scope | 200 on the verify, and the profile shows the new email |
| PROF_ABHA_604, re-KYC | `m1_post_v3_profile_account_request_otp_re_kyc`, the OTP, `m1_post_v3_profile_account_verify_re_kyc` | 200 on the verify, and the profile shows `kycVerified` `true` |
| PROF_ABHA_605, delete or deactivate | ABDM's M1 specification publishes no delete or deactivate operation | `not-run`, with that reason |

### TAGGING_UNIQUEPATIENTID_UNIQUEABHANUMBER: one ABHA per patient id

Mandatory. `screen`. Your system checks whether an ABHA number already exists in its database before it creates a patient id, on both the creation and the verification paths, so one ABHA never maps to two of your patients and one of your patients never holds two ABHAs.

Evidence: verify the same ABHA twice in a run. The second time, the screen says the record is already linked and names your patient id, and the database holds one row. `hiecm.concept.m1-avoiding-duplicate-abha`

Loop limit: 3 passes per test case.

### SHARE_PATIENT_PROFILE_701: share a profile by scanning the facility QR

This case is run from the person's ABHA app, and the call that proves it lands on your side as the `on-share` webhook. It belongs to the scan and register skill, `abdm-scan-and-register`, which carries the webhook and the token reply. Record it there. In this manifest, write `see abdm-scan-and-register`.

## When the last case is recorded

Write the manifest. It is the whole report. Case ids to request ids, nothing else, so a reviewer checks it against the gateway's own record rather than reading screenshots. Secrets never appear in it: no tokens, no OTPs, no Aadhaar numbers, no client secret.

```json
{
  "skill": "abdm-m1",
  "set": "M1 ABHA creation and verification, NHA, version 1.1",
  "entity": "private",
  "run_started": "2026-09-29T10:12:40Z",
  "run_finished": "2026-09-29T11:48:03Z",
  "client_id": "<your sandbox client id>",
  "cases": [
    {"id": "CRT_ABHA_101", "outcome": "passed", "evidence": "sandbox",
     "request_ids": ["6f1c...", "a02d...", "c9e4..."],
     "observed": ["byAadhaar 200 message=Account created successfully", "abha-address 200 healthIdNumber", "profile/account 200 ABHANumber"]},
    {"id": "CRT_ABHA_102", "outcome": "passed", "evidence": "screen",
     "attachment": "consent-2026-09-29.png", "rule": "hiecm.concept.m1-screen-contract"},
    {"id": "CRT_ABHA_105", "outcome": "needs-human", "evidence": "human",
     "request_ids": ["b7a1..."], "reason": "OTP arrives on the person's phone; nobody present"},
    {"id": "CRT_ABHA_401", "outcome": "not-run", "reason": "no enrolment by document operation in the M1 specification"}
  ]
}
```

Then say, in three lines: how many cases passed, failed, need a human and were not run; which mandatory cases for your entity are not `passed`; and the one case to fix first.

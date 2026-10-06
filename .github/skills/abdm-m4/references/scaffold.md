# HIE-CM m4 build

Scaffolds an ABDM m4 integration one journey at a time. It covers creating an HPID, registering a professional on the HPR, and onboarding a facility to the HFR.

## How this skill runs

Every journey below is an OODA loop, not a recipe: observe the actual state (last response, last error), orient against the step matched below, decide the cheapest next action, act, and return to observe. A step is done only when its exit condition is observed against the sandbox, never because it "should have worked."

Loop limit: 8 passes per step. Hitting the limit is an escalation: state what was observed, what was tried, and which operation page to read, then ask one question.

## Before the first journey, when the codebase already exists

Skip this section only for a system that does not exist yet. Otherwise it runs first, and its exit condition is a written plan, not a call.

### In plain words

Most ABDM integrations are not new systems. They are a hospital management
system, a laboratory system or a clinic application that already has patients,
visits, records, a login, an HTTP client and a way of keeping secrets. Every
ABDM journey has to land somewhere inside that, and a journey built before the
codebase has been read lands in the wrong place: a second HTTP client beside the
first, an ABHA column on the wrong table, a callback route the reverse proxy
never forwards.

So the first loop is not a journey. It is a survey of the system as it is, and
its exit condition is a written plan that names, for every ABDM touchpoint, the
file it will live in. The journeys then build against that plan rather than
against the specification's idea of a fresh codebase.

### Before you start

- The repository, checked out, with permission to read all of it. A survey of
  half a codebase produces a plan for half a system.
- The answers to the deployment interview. The
  code says what the system is. Only the integrator can say what the
  deployment is, and the two together decide which journeys are built at all.
- The practices that hold across every call, which
  the plan has to leave room for.

### What happens

This is one loop with a limit of eight passes over the codebase. Each pass
reads live state only, which here means the files themselves, never a README's
description of them and never an assumption carried from a similar system.

**Observe.** Inventory the system from its manifests and its tree, not from its
documentation. Record file paths for each of these, or record that none exists:

| Find | Where it usually shows | Why ABDM needs it |
|---|---|---|
| Languages and runtime versions | package manifests, lock files, toolchain files | Every generated call has to be idiomatic here |
| Build, run and test commands | manifests, CI configuration, a Makefile | Each journey's exit condition becomes a test that runs the same way |
| The frontend and backend split, and how they talk | the top level tree, an API client in the frontend, route definitions in the backend | The counter screens go in the frontend; every ABDM call goes through the backend |
| The outbound HTTP client the backend already uses | the dependency list, a shared client module | ABDM calls reuse it, or a second one appears and the two drift |
| How secrets and configuration reach the process | environment loading, a vault client, a config file | The client id, the secret and the access token travel the same way |
| The patient model, and the identifier fields it already carries | the schema, the ORM models, the migrations | The ABHA number and address become columns beside the existing identifiers, not a new table |
| The visit, encounter or record model | the same places | A care context maps to one of these, and the plan has to say which |
| Where inbound HTTP is routed and authenticated, and whether the deployment has a public URL | the router, the middleware, the reverse proxy configuration, the deployment manifests | ABDM calls back, and a callback route that nothing forwards is silence nobody notices |
| Existing cryptography helpers | a security or crypto module, the dependency list | The RSA encryption of identifiers reuses them |
| Where errors are shown to a user, and where they are logged | the frontend's error surface, the logging setup | A refused call has to land on the screen the person is looking at, and never log a token |

**Orient.** Map each ABDM touchpoint onto that inventory. Where the map is
exact, write the file path. Where it is not, write two candidates and say what
would decide between them. The common ambiguities: two places that could hold
the patient identifier, an HTTP client in the frontend and none in the backend,
a monorepo with several services and no obvious owner for callbacks.

Then read the interview answers against the inventory. A government integrator
gets the demographic route; a facility with no public URL gets no callback
driven journey until it has one; a desk with a fingerprint reader gets the
biometric method. The route set is the intersection of what the deployment
allows and what the code can host.

**Decide.** Order the journeys. The token comes first because every other call
needs it: the gateway session token, or for M4 the bearer token the registry calls
carry. Then the journey whose exit condition can be observed with
the least new code, usually a profile read for a patient who already holds an
ABHA. Creation and linking come after, because each depends on state the earlier
ones produce. For each journey, name the files it will touch and the test that
proves its exit condition.

**Act.** Write the plan. It is a file in the repository, at the path the
integrator names or at the root as `abdm-integration-plan.md`, and it is the
only output of this loop. Then return to observe once, reading the plan against
the tree, to confirm every path in it exists or is marked as new.

If the limit is reached with questions still open, escalate: name what was
found, name the two candidates that could not be separated, point at this
atom, and ask one question.

### How you know it worked

The plan exists and answers every row of the inventory table with a file path,
or with the words none, add at, followed by a path. No row is blank and no row
says to be decided.

Every ABDM touchpoint in the plan names one file, or names two candidates and
the observation that would choose between them. Every journey in the plan names
the test that proves its exit condition and the command that runs it.

Open the plan beside the tree. Every path it names resolves, or is marked as
new. That is the observation that ends this loop, and the first journey does
not start until it has been made.

### When it goes wrong

- **The plan puts the HTTP client in the frontend.** The survey found the
  frontend's API client and stopped. Every ABDM call carries a secret, so it
  goes through the backend, and the plan has to say which backend module.
- **Two patient tables, and the plan picked one.** Orient produced one
  hypothesis where it needed two. Name both, and name the query that shows
  which one the visit model points at.
- **The plan has a callback route and the deployment has no public URL.** The
  inventory row on inbound routing was answered from the router rather than
  from the deployment. Mark every callback driven journey as blocked on a URL,
  and build the ones that are not.
- **The survey read the README and not the tree.** A README describes the
  system somebody meant to build. The plan is for the one that exists.
- **Eight passes and the plan is still incomplete.** Escalate with the rows
  that are answered, the rows that are not, this atom, and one question about
  the row that blocks the most journeys.

From `shared.concept.survey-an-existing-codebase`.

## Journeys

### HPID, registration via Aadhaar (`m4-registration-api-s-collection-via-aadhaar`)

**Act: the calls in this journey, in order**

#### 1. Generate Aadhaar link (`m4_post_aadhaar_generatelink`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/aadhaar/generateLink \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "scopes": [
    "nhpr-register"
  ],
  "source": "NHPR"
}'
```

#### 2. Submit the is Aadhaar authenticated (`m4_post_aadhaar_isauthenticated`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/aadhaar/isAuthenticated \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "259813b1-a339-4482-8df5-16ee45b8dcf2"
}'
```

#### 3. Verify OTP (`m4_post_v2_registration_aadhaar_verifyotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v2/registration/aadhaar/verifyOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "de4ff682-fcc6-4bcf-a978-0dbb19a288b4"
}'
```

#### 4. Submit the demographic auth via mobile (`m4_post_v2_registration_aadhaar_demographicauthviamobile`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v2/registration/aadhaar/demographicAuthViaMobile \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "<TXN_ID>",
  "mobileNumber": "<MOBILE_NUMBER>"
}'
```

#### 5. Submit the account exist (`m4_post_v1_registration_aadhaar_checkhpidaccountexist`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/registration/aadhaar/checkHpIdAccountExist \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "de4ff682-fcc6-4bcf-a978-0dbb19a288b4"
}'
```

#### 6. Get suggesstion (`m4_post_v1_registration_aadhaar_hpid_suggestion`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/registration/aadhaar/hpid/suggestion \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "a825f76b-0696-40f3-864c-5a3a5b389a83"
}'
```

#### 7. Generate mobile OTP (`m4_post_v1_registration_aadhaar_generatemobileotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/registration/aadhaar/generateMobileOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "mobile": "981065XXXX",
  "txnId": "de4ff682-fcc6-4bcf-a978-0dbb19a288b4"
}'
```

#### 8. Verify mobile OTP (`m4_post_v1_registration_aadhaar_verifymobileotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/registration/aadhaar/verifyMobileOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "otp": "<BASE64 ENCODED STRING>",
  "txnId": "de4ff682-fcc6-4bcf-a978-0dbb19a288b4"
}'
```

#### 9. Create HPR ID V2 (`m4_post_v2_registration_aadhaar_createhpridwithpreverified`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v2/registration/aadhaar/createHprIdWithPreVerified \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "idType": "hpr_id",
  "domainName": "@hpr.abdm",
  "email": "<ABHA_ADDRESS>.com",
  "firstName": "Ayushman",
  "middleName": "Bharat",
  "lastName": "Mission",
  "password": "Ayushman@143",
  "profilePhoto": "<BASE64 ENCODED STRING>",
  "txnId": "c3b0c27d-e19d-4244-b8bb-3fa19285054a",
  "hprId": "<EMAIL>",
  "sourceType": "DRIVING_LICENSE",
  "hpCategoryCode": 1,
  "hpSubCategoryCode": 1,
  "clientId": "V4",
  "stateCode": "<STATE_CODE>",
  "districtCode": "<DISTRICT_CODE>",
  "council": false,
  "role": 0
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "token": "<TOKEN>",
  "hprIdNumber": "<HPR_ID_NUMBER>",
  "name": "<NAME>",
  "gender": "<GENDER>",
  "yearOfBirth": "<YEAR_OF_BIRTH>",
  "monthOfBirth": "<MONTH_OF_BIRTH>",
  "dayOfBirth": "<DAY_OF_BIRTH>",
  "firstName": "<FIRST_NAME>",
  "hprId": "<HPR_ID>",
  "lastName": "<LAST_NAME>",
  "middleName": "<MIDDLE_NAME>",
  "stateCode": "<STATE_CODE>",
  "districtCode": "<DISTRICT_CODE>",
  "subDistrictCode": "<SUB_DISTRICT_CODE>",
  "subDistrictName": "<SUB_DISTRICT_NAME>",
  "stateName": "<STATE_NAME>",
  "districtName": "<DISTRICT_NAME>",
  "email": "<EMAIL>",
  "kycPhoto": "<KYC_PHOTO>",
  "mobile": "<MOBILE>",
  "categoryId": 0,
  "subCategoryId": 0,
  "role": 0,
  "authMethods": [
    "AADHAAR_OTP"
  ],
  "new": false
}
```

### HPID, categories (`m4-util`)

**Act: the calls in this journey, in order**

#### 1. Fetch HPID categories (`m4_get_hpid_get_categories`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/hpid/get/categories \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 2. Fetch HPID sub categories from category (`m4_get_hpid_get_subcategories`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/hpid/get/subCategories \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
[
  {
    "code": "220",
    "name": "Yoga and Naturopathy"
  },
  {
    "code": "1",
    "name": "Modern Medicine"
  },
  {
    "code": "2",
    "name": "Dentist"
  }
]
```

### HPR, authentication (`m4-authentication`)

**Act: the calls in this journey, in order**

#### 1. Login via password (`m4_post_v1_auth_authpassword`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/api/v1/auth/authPassword \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "idType": "",
  "domainName": "",
  "hprId": "<HPR_ID>",
  "password": "XXXX@992"
}'
```

#### 2. Get public certificate (`m4_get_v1_auth_cert`)

```bash
curl --request GET \
  --url "https://apihspsbx.abdm.gov.in/v4/int/api/v1/auth/cert?publicCertificateRequestDto=<PUBLICCERTIFICATEREQUESTDTO>" \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 3. Verify Aadhaar OTP (`m4_post_v1_auth_confirmwithaadhaarotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/api/v1/auth/confirmWithAadhaarOtp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "otp": "308709",
  "txnId": "de4ff682-fcc6-4bcf-a978-0dbb19a288b4"
}'
```

#### 4. Send via Aadhaar OTP (`m4_post_v1_auth_init`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/api/v1/auth/init \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "idType": "",
  "domainName": "",
  "authMethod": "AADHAAR_OTP",
  "hprId": "<HPR_ID>"
}'
```

#### 5. Send verify OTP (`m4_post_v2_auth_loginviamobilesendotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/api/v2/auth/loginViaMobileSendOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "4c8c4b29-6d7e-4446-8f73-4574d6d14f09",
  "mobile": "97624XXXXX"
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "txnId": "28b4ce41-71df-48af-8b6c-13c30402816c",
  "mobileNumber": "******1234"
}
```

### HPR, contact verification (`m4-verification`)

**Act: the calls in this journey, in order**

#### 1. Generate mobile OTP 2 (`m4_post_v1_doctors_generate_mobile_otp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/generate-mobile-otp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hpr_token": "<JWT TOKEN>",
  "officialMobile": "<BASE64 ENCODED STRING>"
}'
```

#### 2. Send verification email (`m4_post_v1_doctors_generate_verification_email`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/generate-verification-email \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "emailAddress": "<ABHA_ADDRESS>.com",
  "otp_type": ""
}'
```

#### 3. Submit the regenerate mobile OTP (`m4_post_v1_doctors_regenerate_mobile_otp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/regenerate-mobile-otp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hpr_token": "<JWT TOKEN>",
  "officialMobile": "PFiI0AQJkAKIdLL6ytdJLKFObqXab9rwTvOEPHflksQBkMzIIb8HMDYUzZfN3AUdefedSbb+B4sPwi72lsaaNRkpXygWRF0GWntEwD/WL80JbXaW9DJkwPpDEzQpMYKKT17iCTp7pQer8337NZofO1D1aYiDfEnA9E1HMTyPCGFjvmbcL32hNqGsgpHKYNh4rHXCo4RwP5UQKWDYI1jLZqbWLp0a9GQu9nC1hyP5IR5LRCASzvhiRfrRk+Y660xuDSCvOKb+uUPcN3ZFA==xxxxxxxx"
}'
```

#### 4. Resend verification email (`m4_post_v1_doctors_resent_verify_email`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/resent-verify-email \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "emailAddress": "<ABHA_ADDRESS>.com",
  "otp_type": ""
}'
```

#### 5. Verify email OTP (`m4_post_v1_doctors_verify_email_otp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/verify-email-otp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hpr_token": "<JWT TOKEN>",
  "hpr_id": "<HPR_ID>",
  "officialEmail": "<ABHA_ADDRESS>.com",
  "emailOtp": 515999
}'
```

#### 6. Verify mobile OTP (`m4_post_v1_doctors_verify_mobile_otp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/verify-mobile-otp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hpr_token": "<JWT TOKEN>",
  "txnId": "dd392164-0f4a-4894-8d64-1fce027ee033",
  "otp": "<BASE64 ENCODED STRING>"
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "status": "<string>",
  "txnId": "<string>"
}
```

### HPR, professional registration (`m4-enrollment`)

**Act: the calls in this journey, in order**

#### 1. Register professional (`m4_post_v1_doctors_register_professional_new`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/register-professional-new \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "practitioner": {
    "personalInformation": "<PERSONAL_INFORMATION>",
    "communicationAddress": "<COMMUNICATION_ADDRESS>",
    "contactInformation": "<CONTACT_INFORMATION>",
    "registrationAcademic": "<REGISTRATION_ACADEMIC>",
    "specialities": [
      "<SPECIALITIES>"
    ],
    "currentWorkDetails": "<CURRENT_WORK_DETAILS>",
    "apiClientId": "<API_CLIENT_ID>",
    "profilePhoto": "<PROFILE_PHOTO>",
    "healthProfessionalType": "<HEALTH_PROFESSIONAL_TYPE>",
    "officialMobileCode": "<OFFICIAL_MOBILE_CODE>",
    "officialMobile": "<OFFICIAL_MOBILE>",
    "officialMobileStatus": "<OFFICIAL_MOBILE_STATUS>",
    "officialEmail": "<OFFICIAL_EMAIL>",
    "officialEmailStatus": "<OFFICIAL_EMAIL_STATUS>",
    "visibleProfilePicture": "<VISIBLE_PROFILE_PICTURE>",
    "profileVisibleToPublic": "<PROFILE_VISIBLE_TO_PUBLIC>",
    "addressAsPerKYC": "<ADDRESS_AS_PER_KYC>"
  },
  "hprToken": "<HPR_TOKEN>"
}'
```

#### 2. Update professional (`m4_post_v1_doctors_update_professional_new`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/update-professional-new \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "practitioner": {
    "personalInformation": "<PERSONAL_INFORMATION>",
    "communicationAddress": "<COMMUNICATION_ADDRESS>",
    "contactInformation": "<CONTACT_INFORMATION>",
    "registrationAcademic": "<REGISTRATION_ACADEMIC>",
    "specialities": [
      "<SPECIALITIES>"
    ],
    "currentWorkDetails": "<CURRENT_WORK_DETAILS>",
    "apiClientId": "<API_CLIENT_ID>",
    "profilePhoto": "<PROFILE_PHOTO>",
    "healthProfessionalType": "<HEALTH_PROFESSIONAL_TYPE>",
    "officialMobileCode": "<OFFICIAL_MOBILE_CODE>",
    "officialMobile": "<OFFICIAL_MOBILE>",
    "officialMobileStatus": "<OFFICIAL_MOBILE_STATUS>",
    "officialEmail": "<OFFICIAL_EMAIL>",
    "officialEmailStatus": "<OFFICIAL_EMAIL_STATUS>",
    "visibleProfilePicture": "<VISIBLE_PROFILE_PICTURE>",
    "profileVisibleToPublic": "<PROFILE_VISIBLE_TO_PUBLIC>",
    "addressAsPerKYC": "<ADDRESS_AS_PER_KYC>"
  },
  "hprToken": "<HPR_TOKEN>"
}'
```

#### 3. Fetch documents (`m4_post_v1_doctors_fetch_documents_list`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/fetch-documents-list \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hprid": "<HPR_ID>"
}'
```

#### 4. Upload documents (`m4_post_v1_uploads_upload_document`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/uploads/upload-document \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hpr_token": "<HPR_TOKEN>",
  "document": [
    {
      "document_id": 0,
      "document_type": "<DOCUMENT_TYPE>",
      "fileType": "<FILE_TYPE>",
      "data": [
        "<DATA>"
      ]
    }
  ]
}'
```

#### 5. Get professional info (`m4_post_v1_doctors_fetch_professional_info`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/doctors/fetch-professional-info \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "practitioner": {
    "id": "<HPR_ID>",
    "name": "",
    "contactNumber": "976243XXXX",
    "state": "UTTAR PRADESH",
    "registrationNumber": ""
  }
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "message": "<MESSAGE>"
}
```

### HPR, master data (`m4-utility`)

**Act: the calls in this journey, in order**

#### 1. Get all affiliated board (`m4_get_v1_masters_affiliated_board`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/affiliated-board \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 2. Get affiliated board by state ID (`m4_get_v1_masters_affiliated_board_states_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/affiliated-board/states/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 3. Get affiliated board by ID (`m4_get_v1_masters_affiliated_board_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/affiliated-board/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 4. Get college by state (`m4_get_v1_masters_colleges_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/colleges/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 5. Get college by state and medicine ID (`m4_get_v1_masters_colleges_stateid_medicineid`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/colleges/{stateId}/{medicineId} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 6. Get all countries (`m4_get_v1_masters_countries`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/countries \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 7. Get countries by ID (`m4_get_v1_masters_countries_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/countries/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 8. List courses (`m4_post_v1_masters_courses`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/courses \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "systemOfMedicine": "Registered Auxiliary Nurse Midwife(RANM)",
  "hprType": "nurse",
  "qualificationCount": 0
}'
```

#### 9. Get all districts (`m4_get_v1_masters_district`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/district \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 10. Get districts by state (`m4_get_v1_masters_district_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/district/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 11. List government health programmes (`m4_get_v1_masters_languages`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/languages \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 12. Get pi languages by ID (`m4_get_v1_masters_languages_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/languages/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 13. Get all medical council (`m4_get_v1_masters_medical_councils`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/medical-councils \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 14. Get medical council by system of medicine name (`m4_get_v1_masters_medical_councils_name`)

```bash
curl --request GET \
  --url "https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/medical-councils/name?medicineName=<MEDICINENAME>" \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 15. Get all nurse councils (`m4_get_v1_masters_nurse_councils`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/nurse-councils \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 16. Get all states (`m4_get_v1_masters_states`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/states \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 17. Get status (`m4_get_v1_masters_states_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/states/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 18. Get all sub districts (`m4_get_v1_masters_sub_districts`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/sub-districts \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 19. Get all sub districts 1 (`m4_get_v1_masters_sub_districts_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/sub-districts/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 20. Get all medical system (`m4_get_v1_masters_system_of_medicines`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/system-of-medicines \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 21. List all university (`m4_get_v1_masters_universites`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/universites \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 22. Get university by college (`m4_get_v1_masters_universites_id`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/apis/v1/masters/universites/{id} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
[
  {
    "id": 0,
    "name": "<NAME>",
    "status": false,
    "visibleStatus": false,
    "collegeId": 0,
    "collegeName": "<COLLEGE_NAME>",
    "deleted": false,
    "college": "<COLLEGE>"
  }
]
```

### HPR, profile and password (`m4-profile`)

**Act: the calls in this journey, in order**

#### 1. Change password (`m4_post_password_change_bypassword`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/change/byPassword \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "oldPassword": "<OLD_PASSWORD>",
  "newPassword": "<NEW_PASSWORD>",
  "txnId": "<TXN_ID>",
  "hprID": "<HPR_ID>",
  "otp": "<OTP>"
}'
```

#### 2. Recover password via Aadhaar (`m4_post_password_recover_byaadhaar`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/recover/byAadhaar \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hprId": "<HPR_ID>"
}'
```

#### 3. Generate mobile OTP 1 (`m4_post_password_recover_bymobile_sendmobileotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/recover/byMobile/sendMobileOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "hprId": "amol.xxxxxx"
}'
```

#### 4. Verify mobile OTP 1 (`m4_post_password_recover_bymobile_verifymobileotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/recover/byMobile/verifyMobileOTP \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "oldPassword": "<OLD_PASSWORD>",
  "newPassword": "<NEW_PASSWORD>",
  "txnId": "<TXN_ID>",
  "hprID": "<HPR_ID>",
  "otp": "<OTP>"
}'
```

#### 5. Recover password confirm by Aadhaar (`m4_post_password_recover_confirmbyaadhaar`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/recover/confirmByAadhaar \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "newPassword": "<NEW_PASSWORD>",
  "otp": "<OTP>",
  "txnId": "5f7a4a1e-59ba-4c0c-9e0c-8e6b3b6e2f11"
}'
```

#### 6. Reset password and session (`m4_post_password_reset_password`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/reset/password \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "newPassword": "<NEW_PASSWORD>",
  "otp": "<OTP>",
  "txnId": "5f7a4a1e-59ba-4c0c-9e0c-8e6b3b6e2f11"
}'
```

#### 7. Reset password (`m4_post_password_resetpassword`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/password/resetPassword \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "newPassword": "<NEW_PASSWORD>",
  "otp": "<OTP>",
  "txnId": "5f7a4a1e-59ba-4c0c-9e0c-8e6b3b6e2f11"
}'
```

#### 8. Get account png card (`m4_get_v1_account_getidcard`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/account/getIdCard \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'X-Token: <X_TOKEN>'
```

#### 9. Get user profile by JWT (`m4_get_v1_account_information`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/account/information \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 10. Get user details (`m4_get_v1_account_user_details_hprid`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/account/user-details/{hprId} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 11. Logout (`m4_get_v4_auth_logout`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v4/auth/logout \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
"User Profile LoggedOut Successfully!!"
```

### HPR, recover the HPR ID (`m4-forgot-healthcare-professional-id-number`)

**Act: the calls in this journey, in order**

#### 1. Submit the retrieval health ID by Aadhaar (`m4_post_v1_forgot_hprid_aadhaar`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/forgot/hprId/aadhaar \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "otp": "<BASE64 ENCODED STRING>",
  "txnId": "4c115e27-a602-4320-b4cd-ee658539e2f0"
}'
```

#### 2. Submit the retrieval health ID by mobile (`m4_post_v1_forgot_hprid_mobile`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/forgot/hprId/mobile \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "txnId": "5f7a4a1e-59ba-4c0c-9e0c-8e6b3b6e2f11",
  "name": "<NAME>",
  "gender": "<GENDER>",
  "yearOfBirth": "<YEAR_OF_BIRTH>",
  "monthOfBirth": "<MONTH_OF_BIRTH>",
  "dayOfBirth": "<DAY_OF_BIRTH>",
  "firstName": "<FIRST_NAME>",
  "lastName": "<LAST_NAME>",
  "middleName": "<MIDDLE_NAME>",
  "otp": "<OTP>"
}'
```

#### 3. Generate mobile OTP (`m4_post_v1_forgot_hprid_mobile_generateotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/forgot/hprId/mobile/generateOtp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "mobileNumber": "VPoaDCJBNyGhJiX+sAh9yRq1WXAfRXkgcE31/0U2DMkH/+nvpspAA4GEmkbideZhKsSLYnFA1lHPkBH7PS6Bg4jz0aSdDAoovnYgVftJ/suP4mzhhg1Hrf7zQFPriHiraNlsIzsDeLl3ckGejNiCmXhfhBBw==xxxxxxxxxxxxx"
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "txnId": "132dd7dd-ca5a-4ec1-a36c-093c007bf794",
  "msg": "Please enter OTP sent on your mobile number ******2021",
  "mobileNumber": "******2021"
}
```

### HPR, search (`m4-searched`)

**Act: the calls in this journey, in order**

#### 1. Get the exists by HPR ID (`m4_get_v1_search_existsbyhprid_hprid`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/search/existsByHprId/{hprId} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 2. Search user by HPR ID (`m4_get_v1_search_searchbyhprid_hprid`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/search/searchByHprId/{hprId} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 3. Search user by mobile no (`m4_get_v1_search_searchbymobile_mobile`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/search/searchByMobile/{mobile} \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
[
  {
    "hprIdNumber": "<HPR_ID>",
    "name": "Ayushman Bharat Mission",
    "authMethods": [
      "PASSWORD",
      "MOBILE_OTP",
      "AADHAAR_OTP"
    ],
    "hprId": "<EMAIL>",
    "categoryId": "1",
    "subCategoryId": "1"
  }
]
```

### HFR, facility onboarding (`m4-onboarding-apis`)

**Act: the calls in this journey, in order**

#### 1. Get filtered address post (`m4_post_search_address_filter_deduplicate`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/search/address/filter/deduplicate \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "name": "Jethana",
  "address": "<ADDRESS>",
  "district": "511",
  "subDistrict": "5271",
  "village": "",
  "geolocation": "",
  "facilityId": "69765"
}'
```

#### 2. Submit the v15Basic facility information (`m4_post_v1_5_facility_basic_information`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/basic-information \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'x-hprid-auth: <X_HPRID_AUTH>' \
  --header 'Content-Type: application/json' \
  --data '{
  "trackingId": "",
  "facilityInformation": {
    "facilityName": "Sahyadri Hospital",
    "facilityAddressDetails": {
      "country": "India",
      "stateLGDCode": "24",
      "districtLGDCode": "438",
      "subDistrictLGDCode": "6512",
      "facilityRegion": "U",
      "villageCityTownLGDCode": "",
      "addressLine1": "townhall, Pune",
      "addressLine2": "Pune",
      "pincode": "<PINCODE>",
      "latitude": "23.068570",
      "longitude": "23.068570"
    },
    "facilityContactInformation": {
      "facilityEmailId": "<ABHA_ADDRESS>.com",
      "facilityContactNumber": "976243xxxx",
      "websiteLink": "nha.abdm.gov.in",
      "facilityLandlineNumber": "",
      "facilityStdCode": ""
    },
    "ownershipCode": "G",
    "ownershipSubTypeCode": "C",
    "ownershipSubTypeCode2": "MOHF",
    "systemOfMedicineCode": "M,D,UN",
    "typeOfServiceCode": "IPD,OPD",
    "facilityTypeCode": "5",
    "specialityTypeCode": "SINGLE",
    "facilityUploads": {
      "facilityBoardPhoto": {
        "name": "",
        "value": ""
      },
      "facilityBuildingPhoto": {
        "name": "",
        "value": ""
      }
    },
    "facilitySubType": "47",
    "facilityOperationalStatus": "F",
    "timingsOfFacility": [
      {
        "workingDays": "MON",
        "openingHours": "9:00 AM - 6:00 PM"
      },
      {
        "workingDays": "TUE",
        "openingHours": "9:00 AM - 4:00 PM"
      },
      {
        "workingDays": "WED",
        "openingHours": "9:00 AM - 6:00 PM"
      }
    ],
    "abdmCompliantSoftware": [
      {
        "existingSoftwares": [
          ""
        ],
        "anyOther": ""
      }
    ]
  }
}'
```

#### 3. Submit the v15Facility additional information (`m4_post_v1_5_facility_additional_information`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/additional-information \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "trackingId": "80266",
  "linkedProgramIds": {
    "nhrrId": "1234",
    "nin": "1234",
    "abpmjayId": "1234",
    "rohiniId": "1234",
    "echsId": "1234",
    "cghsId": "1234",
    "ceaRegistration": "1234",
    "stateInsuranceSchemeId": "1234"
  },
  "generalInformation": {
    "hasDialysisCenter": "YALL",
    "hasPharmacy": "YALL",
    "hasBloodBank": "YALL",
    "hasCathLab": "YALL",
    "hasDiagnosticLab": "YALL",
    "hasImagingCenter": "YALL",
    "servicesByImagingCenter": [
      {
        "service": "S36",
        "count": 7
      },
      {
        "service": "S16",
        "count": 5
      },
      {
        "service": "S23",
        "count": 3
      }
    ]
  }
}'
```

#### 4. Submit the v15Facility detailed information (`m4_post_v1_5_facility_detailed_information`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/detailed-information \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "trackingId": "80266",
  "specialities": [
    {
      "systemOfMedicineCode": "M",
      "isSpecializationAvalaible": "Y",
      "specialities": [
        "S29",
        "S30",
        "S31"
      ]
    },
    {
      "systemOfMedicineCode": "D",
      "isSpecializationAvalaible": "Y",
      "specialities": [
        "S50",
        "S51",
        "S46"
      ]
    },
    {
      "systemOfMedicineCode": "UN",
      "isSpecializationAvalaible": "Y",
      "specialities": [
        "S68",
        "S168",
        "S100"
      ]
    }
  ],
  "medicalInfrastructure": {
    "countIPDBedsWithoutOxygen": 2,
    "countIPDBedsWithOxygen": 3,
    "countICUBedsWithVentilators": 4,
    "countICUBedsWithoutVentilators": 1,
    "countHDUBedsWithVentilators": 5,
    "countHDUBedsWithoutVentilators": 6,
    "totalNumberOfVentilators": 7,
    "countDayCareBedsWithoutOxygen": 8,
    "countDayCareBedsWithOxygen": 9,
    "countDentalChairs": 1,
    "totalNumberOfBeds": 4
  },
  "pharmacyDetails": {
    "isJanAushadhiKendra": "Y",
    "janAushadhiKendraId": "jan-id",
    "drugLicenseNumber": "test1234",
    "pharmacyGstinNumber": "testg1234",
    "pharmacistRegistrationNumber": "reg1234"
  },
  "bloodBankDetails": {
    "isFacilityRegisteredInERaktkosh": "N",
    "eRaktoshId": "Y",
    "bloodBankLicenseNumber": "345-test-regno",
    "bloodStorageCenters": "Y",
    "storageCentersCount": 7,
    "bloodCollectedPerAnnum": "5",
    "bloodRequiredPerAnnum": "6"
  },
  "imagingServices": [
    {
      "service": "S136",
      "count": 77
    },
    {
      "service": "S139",
      "count": 99
    },
    {
      "service": "S138",
      "count": 76
    }
  ],
  "diagnosticServices": [
    ""
  ]
}'
```

#### 5. Submit the v15Submit facility details (`m4_post_v1_5_facility_submit_facility`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/submit-facility \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'x-hprid-auth: <X_HPRID_AUTH>' \
  --header 'x-hprid-auth-verifier: <X_HPRID_AUTH_VERIFIER>' \
  --header 'Content-Type: application/json' \
  --data '{
  "trackingId": "80266",
  "sourceOfInformation": "HRP_SUB_1",
  "sourceUniqueID": "1234",
  "facilitySuperUser": "STATE_SUPER_1"
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "facilityId": "<FACILITY_ID>",
  "status": "<STATUS>",
  "message": "<MESSAGE>"
}
```

### HFR, master data (`m4-utilities`)

**Act: the calls in this journey, in order**

#### 1. Get PSU details by ministry (`m4_get_getpsudetailsbyministry`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/getPsuDetailsByMinistry \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 2. Get all facility sub type by facility type (`m4_post_v1_5_facility_fetch_facility_sub_type`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/fetch-facility-Sub-type \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "facilityTypeCode": "2"
}'
```

#### 3. Get all facility type by ownership and sys of med (`m4_post_v1_5_facility_fetch_facility_type`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/fetch-facility-type \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "ownershipCode": "<OWNERSHIP_CODE>",
  "systemOfMedicineCode": "<SYSTEM_OF_MEDICINE_CODE>"
}'
```

#### 4. Get master data (`m4_get_v1_5_facility_get_master_data`)

```bash
curl --request GET \
  --url "https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/get-master-data?type=<TYPE>" \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 5. Get all master types (`m4_get_v1_5_facility_get_master_types`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/get-master-types \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 6. Get all sub types by owner ship type and sub type (`m4_post_v1_5_facility_get_owner_subtype`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/get-owner-subtype \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "ownershipCode": "<OWNERSHIP_CODE>",
  "ownerSubtypeCode": "<OWNER_SUBTYPE_CODE>"
}'
```

#### 7. Get all specialities by system of medicine code (`m4_post_v1_5_facility_get_specialities`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/get-specialities \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "systemOfMedicineCode": "<SYSTEM_OF_MEDICINE_CODE>"
}'
```

#### 8. Get all district by state ID (`m4_get_v1_5_facility_lgd_districts`)

```bash
curl --request GET \
  --url "https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/lgd/districts?stateCode=<STATECODE>" \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 9. Get all states by LGD (`m4_get_v1_5_facility_lgd_states`)

```bash
curl --request GET \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/lgd/states \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

#### 10. Get all sub district by district code (`m4_get_v1_5_facility_lgd_subdistricts`)

```bash
curl --request GET \
  --url "https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/lgd/subdistricts?districtCode=<DISTRICTCODE>" \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
[
  {
    "code": "6752",
    "name": "Assar"
  },
  {
    "code": "65",
    "name": "Bhaderwah"
  },
  {
    "code": "6747",
    "name": "Bhagwah"
  }
]
```

### HFR, linkage to the HPR (`m4-hfr-hrp-linkage-apis`)

**Act: the calls in this journey, in order**

#### 1. Send OTP to contact (`m4_post_v1_5_facility_sendotptocontact`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/sendOtpToContact \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "facilityId": "IN2810002702"
}'
```

#### 2. Validate OTP (`m4_post_v1_5_facility_validateotp`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.5/facility/validateOtp \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "facilityId": "IN2810002702",
  "sourceId": "AB-PMJAY",
  "otp": "885210",
  "source": "AB-PMJAY",
  "transactionId": "2ddfc7ec-9a9f-412c-8c50-c2be92da5781"
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "facilityId": "<FACILITY_ID>",
  "status": "<STATUS>",
  "message": "<MESSAGE>",
  "errorStatus": [
    "<ERROR_STATUS>"
  ]
}
```

### HFR, facility search (`m4-search`)

**Act: the calls in this journey, in order**

#### 1. Get facility within radius with filter (`m4_post_facilitymanagement_v1_5_facility_bygeolocation_se_16e590`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/FacilityManagement/v1.5/facility/bygeoLocation/searchWithinRadiusWithFilter \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "centerLat": "<CENTER_LAT>",
  "centerLon": "<CENTER_LON>",
  "radiusInKm": "<RADIUS_IN_KM>",
  "speciality": "<SPECIALITY>",
  "facilityOwnership": "<FACILITY_OWNERSHIP>",
  "abdmSoftware": "<ABDM_SOFTWARE>",
  "hospitalSpecialityType": "<HOSPITAL_SPECIALITY_TYPE>",
  "facilityName": "<FACILITY_NAME>",
  "facilityStatus": "<FACILITY_STATUS>",
  "som": "<SOM>",
  "gender": "<GENDER>",
  "doctorName": "<DOCTOR_NAME>",
  "doctorSystemOfMedicine": "<DOCTOR_SYSTEM_OF_MEDICINE>",
  "languages": "<LANGUAGES>",
  "isIcuBedsAvailable": "<IS_ICU_BEDS_AVAILABLE>",
  "size": "<SIZE>",
  "from": "<FROM>"
}'
```

#### 2. Search facility 1 (`m4_post_facilitymanagement_v1_5_facility_search`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/FacilityManagement/v1.5/facility/search \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "ownershipCode": "P",
  "subDistrictLGDCode": "",
  "pincode": "",
  "facilityName": "hospital",
  "facilityId": "",
  "page": 1,
  "resultsPerPage": 10,
  "stateLGDCode": "27",
  "districtLGDCode": ""
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "facilities": [
    "<FACILITIES>"
  ],
  "message": "<MESSAGE>",
  "totalFacilities": 0,
  "numberOfPages": 0
}
```

### HRP bridge services (`m4-multiple-hrp-api`)

**Act: the calls in this journey, in order**

#### 1. Submit the facility add and update (`m4_post_v1_bridges_mutiplehrpaddupdateservices`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1/bridges/MutipleHRPAddUpdateServices \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "facilityId": "IN0610090166",
  "facilityName": "Singla Eye Center",
  "HRP": [
    {
      "bridgeId": "SBX_00XXXX",
      "hipName": "Singla Eye Center",
      "type": "HIP",
      "active": true
    }
  ]
}'
```

#### 2. Search facility (`m4_post_v1_0_facility_search_facilities`)

```bash
curl --request POST \
  --url https://apihspsbx.abdm.gov.in/v4/int/v1.0/facility/search-facilities \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'Content-Type: application/json' \
  --data '{
  "requestId": "5f7a4a1e-59ba-4c0c-9e0c-8e6b3b6e2f11",
  "timestamp": "<TIMESTAMP>",
  "facility": {
    "facilityName": "<FACILITY_NAME>",
    "systemOfMedicine": "<SYSTEM_OF_MEDICINE>",
    "facilityType": "<FACILITY_TYPE>",
    "state": "<STATE>",
    "district": "<DISTRICT>",
    "photo": "<PHOTO>",
    "ownership": "<OWNERSHIP>"
  }
}'
```

**Exit condition (Observe until this is true)**

A 200 whose body matches:

```json
{
  "referenceNumber": "<REFERENCE_NUMBER>",
  "facilities": [
    "<FACILITIES>"
  ]
}
```

## Where the detail is

- Every operation, with its body fields and responses: /docs/hiecm/v3/api/m4

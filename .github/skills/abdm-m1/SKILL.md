---
name: abdm-m1
description: Use when building, debugging or testing ABDM Milestone 1: creating an ABHA number or address, ABHA login, profile management, or the gateway session token. Carries the endpoints, the required headers, the two token rule, the encryption rule and the error codes its specification's examples return. Also carries the scaffolding loop that builds it flow by flow and the loop from a failed call to a named fix, in references/.
type: skill
domain: m1
agent_consumers:
  - abdm-integration-agent
  - abdm-call-debugger
requires:
  - gateway-session-token
produces:
  - abha-number
  - abha-address
  - user-token
  - abha-profile
can_execute: true
can_orchestrate: false
---

# ABDM M1, create and verify ABHA

Generated from the ABDM Developer Portal on 2026-09-16, catalogue version 2026.09.16. Every fact below comes from a page in that portal, which is the place to look when this file does not carry enough.

This file is a snapshot. Re-download the whole folder from https://docs.abdm.gov.in/skills/abdm-m1/ when it is older than the work you are doing: this router and every file under references/ that it links to. Fetching this file alone leaves those links pointing at files you do not have.
If the abdm-docs MCP server is connected, trust its answers over this file: it serves the current catalogue and stamps every response with its catalogue_version, which you can compare against the version above.

## What you can do with M1

- Create an ABHA for somebody who has none: by Aadhaar OTP, by demographic authentication, by face or fingerprint, or under a parent for a child.
- Log in somebody who already has one, by Aadhaar, mobile, ABHA number or ABHA address.
- Read their profile, which carries the whole registration form: names, date of birth, gender, mobile, address with its codes, and a photograph.
- Find an ABHA somebody has forgotten, and pick the right account when one mobile holds several.
- Show the ABHA card and QR code, and take a profile a patient shares by QR at your counter.
- Update a profile and change a mobile.

What it cannot do yet matters as much. Read **Before anything else** below before assuming a capability is one endpoint away.

## Try asking

- "Add ABHA creation by Aadhaar OTP to this codebase"
- "What has to be in place before my first M1 call?"
- "My M1 call returned ABDM-1017. What is wrong, and how do I fix it?"
- "Walk me through the M1 test cases before go-live"

Loaded with no task? Say in three lines what this skill does. Offer the prompts above. Then ask what the person is building, and whether the code for it exists yet.

## What is in this folder

- **Scaffold.** Survey the codebase first when one exists, then build it flow by flow against the sandbox, as a loop that ends when the step's exit condition holds rather than on a call returning 200. [references/scaffold.md](references/scaffold.md)
- **Design.** What the journey around the calls has to do, and what a screen is forbidden to claim. [references/design.md](references/design.md)
- **Integrate.** 123 operations, with their hosts and headers. [references/integrate.md](references/integrate.md)
- **Debug.** The loop from a failed call to a named fix, and 17 error codes from the specification's examples. [references/debug.md](references/debug.md)
- **Test.** The functional test cases, one loop each, with the evidence the sandbox can vouch for and the manifest that replaces a screenshot report. [references/test.md](references/test.md)

This file is the map. Each line above is a file beside it, opened one at a time rather than read through.

## Before anything else

- Treat every request and response shape in this skill as unconfirmed until the sandbox has answered you. Check a response before you rely on its shape.
- The design section is different in kind. Its rules come from building a working front desk against the sandbox, and each atom it cites names what was observed and the date it was seen.
- ABDM publishes operations, not a user experience. The journey is the integrator's to design, so offer the shape below as a suggestion and build what they ask for instead when they have a view of their own counter.
- The ABHA step comes before the registration form and fills it. A verified profile carries the whole form, so a journey that registers the patient first and offers ABHA afterwards has already spent the keystrokes it existed to save.
- Two ways the profile reaches the desk. The patient scans a QR and consents in their own app, and ABDM posts the profile to your callback, so nobody types or asks anything. Or the desk runs the identifier journey. The filled form is the destination either way.
- Decide deliberately whether a journey can complete without an ABHA. A record keyed by the facility's own number does not need one, and a journey that cannot finish without one blocks care for anyone who has none.
- An identifier and an auth method are two different questions, and listing them together is what makes M1 look like five choices. Ask which identifier first, then offer auth methods underneath it, and only where there is more than one.
- Every identifier starts on the login path, Aadhaar included. A verified login already returns the accounts, and only ABDM-1114 on a refusal means nobody holds one. Create on any other answer and the patient ends up with two numbers, which nothing merges.
- Get an access token first, from the gateway session endpoint. Every other call needs it in `Authorization: Bearer <token>`.
- Two tokens exist and they are not interchangeable. The gateway access token goes in `Authorization`. The user token from an enrolment or a login goes in `X-token`. Profile endpoints need both.
- Sensitive fields travel encrypted. Aadhaar numbers, mobile numbers, email addresses, OTP values and passwords are encrypted before they go in the body, then base64 encoded.
- The certificate response tells you the padding. `GET /v3/profile/public/certificate` returns `{"publicKey", "encryptionAlgorithm"}`. Read that field and translate it for your language. Do not hard code a padding: a constant is right until it is not, and the failure then looks like a bad value rather than a stale constant.
- One path serves several jobs. The `scope` array in the body picks which one, so read it before assuming an endpoint does one thing.
- The accounts array on a login verification already carries ABHANumber, preferredAbhaAddress, name, gender, dob, profilePhoto and kycVerified, so a registration form can fill the moment the OTP verifies and before any profile call.

## Practices that hold across every call

- Read the body, not only the status. A refusal often names the field in its body while the status says nothing useful.
- When ABDM publishes a value, read it rather than hard coding what it currently says. That covers a parameter, such as the encryption algorithm the certificate endpoints return beside the key, and it covers an enumeration. The registries publish theirs as master data calls: councils, courses, colleges, states and districts on the HPR, and facility types and LGD codes on the HFR. A table typed into your source goes stale silently. Purposes and HI types have no master data call: take them from the enumeration in the specification of the call you are making. Refuse to act on a published value you do not recognise rather than falling back to a default.
- Read every field in a response, not the one you came for. The M1 certificate call returns the encryption algorithm next to the key.
- Prove an assumption against a call that is able to disagree with you. A call that refuses every input with one message cannot tell you which input was right.
- Suspect the transport before the data. When a call refuses a value you believe in, check the encryption, the headers and the clock before you doubt the value.
- Do not carry an encryption path from one module to another. Read the certificate and the algorithm from the registry you are calling.
- Never log a sensitive value before you encrypt it, and never send one to a remote service to be encrypted. Both move the leak rather than removing it.
- Generate a fresh REQUEST-ID for every call and log it before sending. Once a call has failed it is the only handle on it.
- Check the host on any sample before you copy it. A request copied whole can be correct in every respect except where it is pointed, and that failure looks like credentials.
- Do not validate an identifier more strictly than the platform does. A schema that types a field as a UUID is not a promise that every value is one. Refusing a value ABDM would have accepted turns your own client into the thing that broke.
- Read a plural response as plural. A verification returns an accounts array and a consent request can produce more than one artefact. Store the collection and decide from its length.
- A documented callback path is not a documented callback payload. Log the whole body on arrival before you parse it, so a handler written against an assumed shape fails where you can see it.
- Decode a token before you use it. A call that hands you a token has not necessarily handed you the token the next call wants, and the claims are base64 that need no library to read.
- When a journey carries the same parameter through two calls, check what each call's specification asks for rather than carrying the first value forward.
- Do not infer which path an identifier belongs to from where that identifier is most discussed. Send every identifier to the lookup first and let the answer pick the path, so nobody who already holds an account is sent to create a second.
- Do not match an error code with string equality. A code may come back bare, as `ABDM-1001`, or with a trailing `: ` separator, as `ABDM-1001: `. Match on the code itself and tolerate the separator.
- Handle a failure that carries no body. Check for an empty body before you parse, or your client throws on the simplest failure there is.
- Back off on an authentication failure rather than retrying, and never loop a credential check.
- Send TIMESTAMP in UTC, ISO-8601 with milliseconds and a trailing Z, as in `2022-10-06T15:10:00.587Z`.
- Cache a public certificate with a validity window rather than forever. A rotation fails every encrypted call at once, and a cache with no expiry cannot recover on its own.

## Where the detail is

- Every endpoint, with its body fields and responses: /docs/hiecm/v3/api/m1
- The flows as diagrams: /docs/hiecm/v3/milestones/m1
- Every error code across modules: /docs/hiecm/v3/reference/error-codes
- Terms: /docs/hiecm/v3/getting-started/glossary

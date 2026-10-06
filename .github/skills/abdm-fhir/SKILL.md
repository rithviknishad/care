---
name: abdm-fhir
description: Use when producing or checking FHIR for ABDM: building NRCES compliant document bundle generation into a codebase, or auditing the bundles an existing FHIR store already emits. Covers the resource profiles ABDM requires, the Composition rules, and the validator to check against.
type: skill
domain: fhir
agent_consumers:
  - abdm-integration-agent
  - abdm-call-debugger
  - fhir-compliance-agent
requires:
  - abdm-docs-mcp
produces:
  - nrces-document-bundle
can_execute: true
can_orchestrate: false
---

# ABDM FHIR

Generated from the ABDM Developer Portal on 2026-09-16, catalogue version 2026.09.16.

This file is a snapshot. Re-download the whole folder from https://docs.abdm.gov.in/skills/abdm-fhir/ when it is older than the work you are doing: this router and every file under references/ that it links to. Fetching this file alone leaves those links pointing at files you do not have.

## What this skill covers

- **Design.** What a generator gets wrong before it reaches a profile table. [references/design.md](references/design.md)
- **Generate.** Build NRCES compliant bundle generation into a codebase. [references/generate.md](references/generate.md)
- **Audit.** Check an existing FHIR store's output against the same profiles. [references/audit.md](references/audit.md)

Open one when the work calls for it. This file is the map, not the material.

## Try asking

- "Add ABDM compliant FHIR bundle generation to this codebase"
- "Audit the FHIR bundles this codebase already emits"

Loaded with no task? Say in three lines what this skill does. Offer the prompts above. Then ask what the person is building, and whether the code for it exists yet.

## Before anything else

- Treat every request and response shape in this skill as unconfirmed until the sandbox has answered you. Check a response before you rely on its shape.
- The design section is different in kind. Its rules come from building a working front desk against the sandbox, and each atom it cites names what was observed and the date it was seen.
- A bundle that validates is not a bundle ABDM accepts. The NRCES profiles are the floor, and the milestone the bundle travels under adds its own rules on top.

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

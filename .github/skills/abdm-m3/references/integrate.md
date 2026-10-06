# Integrate M3, fetch data with consent

The calls themselves: where they live, what they need in their headers, and one request written out in full.

## Hosts

- `https://dev.abdm.gov.in` ABDM gateway, sandbox
- `https://apis.abdm.gov.in` ABDM gateway, production
## Endpoints

16 operations, grouped by the journey they belong to.

### Other operations

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/hiecm/consent/v3/fetch` | Fetch the consent details |
| `POST` | `/api/hiecm/consent/v3/request/hiu/on-notify` | Acknowledge the notification sent when a consent request is approved/denied/rev… |
| `POST` | `/api/hiecm/consent/v3/request/init` | Initiate the consent request |
| `POST` | `/api/hiecm/consent/v3/request/status` | Get consent request status |
| `POST` | `/api/hiecm/data-flow/v3/health-information/notify` | Notifications corresponding to events during data flow |
| `POST` | `/api/hiecm/data-flow/v3/health-information/request` | Health information data request from HIU. |
| `GET` | `/api/hiecm/data-flow/v3/health-information/request/status/{transaction-id}` | Get the current status of the Health Information Request. |
| `GET` | `/api/hiecm/gateway/v3/bridge-service/serviceId/{service-id}` | Fetch the details of a service ID. |
| `GET` | `/api/hiecm/gateway/v3/bridge-services` | Fetch the service ids registered against a bridge. |
| `PATCH` | `/api/hiecm/gateway/v3/bridge/url` | Update the bridge URL. |
| `POST` | `/api/hiecm/gateway/v3/sessions` | Generate access token. |
| `POST` | `/api/v3/hiu/consent/on-fetch` | This is a callback API called by CM to provide fetched consent artefact details… |
| `POST` | `/api/v3/hiu/consent/request/notify` | This is a callback API to notify HIU when consent is APPROVED, DENIED or REVOKE… |
| `POST` | `/api/v3/hiu/consent/request/on-init` | Callback API of consent request for patient HIU. |
| `POST` | `/api/v3/hiu/consent/request/on-status` | Callback API of consent status request. |
| `POST` | `/api/v3/hiu/health-information/on-request` | Health information data request acknowledgement to HIU. |
## Headers

| Header | What it is |
| --- | --- |
| `REQUEST-ID` | Unique UUID for track the end to end request transaction |
| `TIMESTAMP` | Actual time of the request was initiated, ISO 8601 represents date and time by starting with the year, follow… |
| `X-CM-ID` | Suffix of the consent manager to which the request was intended |
| `X-HIU-ID` | Identifier of the health information user to which the request was intended |
## A request, in full

```bash
curl --request POST \
  --url https://dev.abdm.gov.in/api/hiecm/consent/v3/fetch \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'REQUEST-ID: 18235d89-cb13-479d-ad71-7a57d5f669a8' \
  --header 'TIMESTAMP: 2022-10-06T15:10:00.587Z' \
  --header 'X-CM-ID: sbx' \
  --header 'X-HIU-ID: IN2810014366' \
  --header 'Content-Type: application/json' \
  --data '{
  "consentId": "5f7a535d-a3fd-416b-b069-c97d021fbacd"
}'
```

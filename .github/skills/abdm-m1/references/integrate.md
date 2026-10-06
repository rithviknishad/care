# Integrate M1, create and verify ABHA

The calls themselves: where they live, what they need in their headers, and one request written out in full.

## Hosts

- `https://abhasbx.abdm.gov.in` ABHA service, sandbox
- `https://dev.abdm.gov.in` ABDM gateway, sandbox
- `https://apis.abdm.gov.in` ABDM gateway, production
## Endpoints

123 operations, grouped by the journey they belong to.

### Other operations

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/abha/api/v3.1/profile/login/verify` | Login via Face Auth (QR) - verify |
| `POST` | `/abha/api/v3.1/profile/login/verify` | Login via Biometric (Fingerprint) - v3.1 single step |
| `POST` | `/abha/api/v3.1/profile/login/verify` | Login via Biometric (Iris) - v3.1 single step |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify email OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify email OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify email OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify email OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify mobile OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify mobile OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify mobile OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/auth/byAbdm` | After ABHA creation - verify mobile OTP (optional) |
| `POST` | `/abha/api/v3/enrollment/enrol/abha-address` | After ABHA creation - create ABHA address |
| `POST` | `/abha/api/v3/enrollment/enrol/abha-address` | After ABHA creation - create ABHA address |
| `POST` | `/abha/api/v3/enrollment/enrol/abha-address` | After ABHA creation - create ABHA address |
| `POST` | `/abha/api/v3/enrollment/enrol/abha-address` | After ABHA creation - create ABHA address |
| `POST` | `/abha/api/v3/enrollment/enrol/auth/init` | Face auth - generate transaction ID (init) |
| `POST` | `/abha/api/v3/enrollment/enrol/auth/init` | Face auth - generate transaction ID (init) |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create Child ABHA |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create Child ABHA |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - Demographic authentication (Demo Auth) |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - Demographic authentication (Demo Auth) |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - Aadhaar face authentication |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - Aadhaar fingerprint (bio) |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - Aadhaar IRIS |
| `POST` | `/abha/api/v3/enrollment/enrol/byAadhaar` | Create ABHA - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/enrollment/enrol/capturePID` | Face auth - capture PID / track status |
| `POST` | `/abha/api/v3/enrollment/enrol/capturePID` | Face auth - capture PID / track status |
| `POST` | `/abha/api/v3/enrollment/enrol/capturePID` | Face auth - capture PID / track status |
| `GET` | `/abha/api/v3/enrollment/enrol/suggestion` | After ABHA creation - get ABHA address suggestions |
| `GET` | `/abha/api/v3/enrollment/enrol/suggestion` | After ABHA creation - get ABHA address suggestions |
| `GET` | `/abha/api/v3/enrollment/enrol/suggestion` | After ABHA creation - get ABHA address suggestions |
| `GET` | `/abha/api/v3/enrollment/enrol/suggestion` | After ABHA creation - get ABHA address suggestions |
| `GET` | `/abha/api/v3/enrollment/profile/children` | Get Child ABHA list of the parent |
| `GET` | `/abha/api/v3/enrollment/profile/children` | Get Child ABHA list of the parent |
| `POST` | `/abha/api/v3/enrollment/request/otp` | Send Aadhaar OTP for ABHA enrolment |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify email (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify email (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify email (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify email (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify mobile (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify mobile (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify mobile (optional) |
| `POST` | `/abha/api/v3/enrollment/request/otp` | After ABHA creation - send OTP to verify mobile (optional) |
| `POST` | `/abha/api/v3/phr/web/login/abha/request/otp` | ABHA address login via Aadhaar OTP - send OTP |
| `POST` | `/abha/api/v3/phr/web/login/abha/request/otp` | ABHA address login via Fingerprint - send authentication request |
| `POST` | `/abha/api/v3/phr/web/login/abha/request/otp` | ABHA address login via IRIS - send authentication request |
| `POST` | `/abha/api/v3/phr/web/login/abha/request/otp` | ABHA address login via Mobile OTP - send OTP |
| `POST` | `/abha/api/v3/phr/web/login/abha/search` | Search ABHA address (auth methods) |
| `POST` | `/abha/api/v3/phr/web/login/abha/search` | Search ABHA address (auth methods) |
| `POST` | `/abha/api/v3/phr/web/login/abha/verify` | ABHA address login via Aadhaar OTP - verify |
| `POST` | `/abha/api/v3/phr/web/login/abha/verify` | ABHA address login via Fingerprint - verify |
| `POST` | `/abha/api/v3/phr/web/login/abha/verify` | ABHA address login via IRIS - verify |
| `POST` | `/abha/api/v3/phr/web/login/abha/verify` | ABHA address login via Mobile OTP - verify |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha-profile` | Get ABHA-address profile |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha-profile` | Get ABHA-address profile |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha-profile` | Get ABHA-address profile |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha-profile` | Get ABHA-address profile |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/phr-card` | Get PHR card |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/phr-card` | Get PHR card |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/phr-card` | Get PHR card |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/phr-card` | Get PHR card |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/qr-code` | Get ABHA-address QR code |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/qr-code` | Get ABHA-address QR code |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/qr-code` | Get ABHA-address QR code |
| `GET` | `/abha/api/v3/phr/web/login/profile/abha/qr-code` | Get ABHA-address QR code |
| `GET` | `/abha/api/v3/profile/account` | Get ABHA profile |
| `PATCH` | `/abha/api/v3/profile/account` | Update Child ABHA profile |
| `PATCH` | `/abha/api/v3/profile/account` | Update Child ABHA profile |
| `GET` | `/abha/api/v3/profile/account/abha-card` | Retrieve ABHA card image |
| `POST` | `/abha/api/v3/profile/account/abha/search` | Search ABHA by mobile |
| `POST` | `/abha/api/v3/profile/account/abha/search` | Search ABHA by mobile |
| `POST` | `/abha/api/v3/profile/account/abha/search` | Search ABHA by mobile |
| `POST` | `/abha/api/v3/profile/account/abha/search` | Search ABHA by mobile |
| `POST` | `/abha/api/v3/profile/account/abha/search` | Search ABHA by mobile |
| `GET` | `/abha/api/v3/profile/account/download-abha-card` | Download ABHA card |
| `GET` | `/abha/api/v3/profile/account/qrCode` | Get ABHA QR code |
| `POST` | `/abha/api/v3/profile/account/request/otp` | Child ABHA KYC - send Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/request/otp` | Child ABHA KYC - send Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/request/otp` | Re-KYC - send Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/request/otp` | Update mobile - send OTP |
| `GET` | `/abha/api/v3/profile/account/request/token` | Refresh user token |
| `POST` | `/abha/api/v3/profile/account/verify` | Child ABHA KYC - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/verify` | Child ABHA KYC - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/verify` | Re-KYC - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/account/verify` | Update mobile - verify OTP |
| `GET` | `/abha/api/v3/profile/benefit/abha/{abhanumber}` | Get benefits linked to an ABHA number |
| `POST` | `/abha/api/v3/profile/benefit/linkAndDelink` | Link / De-link benefit using ABHA number |
| `POST` | `/abha/api/v3/profile/benefit/linkAndDelink` | Link / De-link benefit using X-token |
| `POST` | `/abha/api/v3/profile/benefit/linkAndDelink` | Link / De-link benefit using xmlUid |
| `POST` | `/abha/api/v3/profile/benefit/search` | Benefit search by ABHA number |
| `POST` | `/abha/api/v3/profile/benefit/search` | Benefit search by xmlUid |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via Aadhaar number - send Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via ABHA number - send Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via ABHA number - send ABHA (mobile) OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via Biometric (Fingerprint) - send authentication request |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via Biometric (Iris) - send authentication request |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Find ABHA via Aadhaar OTP - send OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Find ABHA via Face - send authentication request |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Find ABHA via Fingerprint - send authentication request |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Find ABHA via IRIS - send authentication request |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Find ABHA via Mobile - send OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Forgot ABHA via Aadhaar - send OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Forgot ABHA via Mobile - send OTP |
| `POST` | `/abha/api/v3/profile/login/request/otp` | Login via Mobile number - send OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via Aadhaar number - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via ABHA number - verify Aadhaar OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via ABHA number - verify ABHA (mobile) OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via Biometric (Fingerprint) - verify |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via Biometric (Iris) - verify |
| `POST` | `/abha/api/v3/profile/login/verify` | Find ABHA via Aadhaar OTP - verify OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Find ABHA via Face - verify |
| `POST` | `/abha/api/v3/profile/login/verify` | Find ABHA via Fingerprint - verify |
| `POST` | `/abha/api/v3/profile/login/verify` | Find ABHA via IRIS - verify |
| `POST` | `/abha/api/v3/profile/login/verify` | Find ABHA via Mobile - verify OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Forgot ABHA via Aadhaar - verify OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Forgot ABHA via Mobile - verify OTP |
| `POST` | `/abha/api/v3/profile/login/verify` | Login via Mobile number - verify OTP |
| `POST` | `/abha/api/v3/profile/login/verify/user` | Login via Mobile number - verify user (select ABHA) |
| `GET` | `/abha/api/v3/profile/public/certificate` | Get public certificate (RSA encryption key) |
| `GET` | `/api/hiecm/gateway/v3/bridge-service/serviceId/{service-id}` | Fetch the details of a service ID. |
| `GET` | `/api/hiecm/gateway/v3/bridge-services` | Fetch the service ids registered against a bridge. |
| `PATCH` | `/api/hiecm/gateway/v3/bridge/url` | Update the bridge URL. |
| `POST` | `/api/hiecm/gateway/v3/sessions` | Generate access token. |
## Headers

| Header | What it is |
| --- | --- |
| `REQUEST-ID` | Unique UUID for every request. |
| `TIMESTAMP` | Current UTC timestamp in ISO-8601 format. |
| `BENEFIT_NAME` | **Applicable for user who is enrolling via Benefit Program.** |
| `X-token` | **Applicable for child abha creation. X-token of Parent user, user can get X-token after login to the system** |
| `TRANSACTION_ID` | Transaction ID from the ABHA creation response. |
| `Content-Type` | `application/json`. |
| `R-token` | Refresh token (`Bearer <refreshToken>`) received at login. |
| `T-token` | Short-lived token (`Bearer <token>`) returned by *Login via Mobile number - verify OTP*. |
| `X-CM-ID` | Suffix of the consent manager to which the request was intended |
## A request, in full

```bash
curl --request POST \
  --url https://abhasbx.abdm.gov.in/abha/api/v3.1/profile/login/verify \
  --header 'Authorization: Bearer <ACCESS_TOKEN_FROM_SESSIONS_CALL>' \
  --header 'REQUEST-ID: 18235d89-cb13-479d-ad71-7a57d5f669a8' \
  --header 'TIMESTAMP: 2022-10-06T15:10:00.587Z' \
  --header 'Content-Type: application/json' \
  --data '{
  "scope": [
    "abha-login",
    "aadhaar-face-login-verify"
  ],
  "authData": {
    "authMethods": [
      "face_auth"
    ],
    "face_login": {
      "txnId": "8220299c-40ad-40b6-bc52-13a7d46a69d0",
      "aadhaar": "{{encrypted aadhaar number}}"
    }
  }
}'
```

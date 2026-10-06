# Integrate M4, register facilities and professionals

The calls themselves: where they live, what they need in their headers, and one request written out in full.

## Hosts

- `https://apihspsbx.abdm.gov.in/v4/int` NHPR, sandbox
- `https://dev.abdm.gov.in` ABDM gateway, sandbox
- `https://apis.abdm.gov.in` ABDM gateway, production
## Endpoints

91 operations, grouped by the journey they belong to.

### Other operations

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/aadhaar/generateLink` | Generate Aadhaar Link |
| `POST` | `/aadhaar/isAuthenticated` | Is Aadhaar Authenticated |
| `GET` | `/api/hiecm/gateway/v3/bridge-service/serviceId/{service-id}` | Fetch the details of a service ID. |
| `GET` | `/api/hiecm/gateway/v3/bridge-services` | Fetch the service ids registered against a bridge. |
| `PATCH` | `/api/hiecm/gateway/v3/bridge/url` | Update the bridge URL. |
| `POST` | `/api/hiecm/gateway/v3/sessions` | Generate access token. |
| `POST` | `/api/v1/auth/authPassword` | Login Via Password |
| `GET` | `/api/v1/auth/cert` | Get Public Certificate |
| `POST` | `/api/v1/auth/confirmWithAadhaarOtp` | Verify Aadhaar OTP |
| `POST` | `/api/v1/auth/init` | Send Via Aadhaar OTP |
| `POST` | `/api/v2/auth/loginViaMobileSendOTP` | Send Verify OTP |
| `POST` | `/apis/v1/doctors/fetch-documents-list` | Fetch Documents |
| `POST` | `/apis/v1/doctors/fetch-professional-info` | Get Professional Info |
| `POST` | `/apis/v1/doctors/generate-mobile-otp` | Generate Mobile OTP 2 |
| `POST` | `/apis/v1/doctors/generate-verification-email` | Send Verification Email |
| `POST` | `/apis/v1/doctors/regenerate-mobile-otp` | Regenerate Mobile OTP |
| `POST` | `/apis/v1/doctors/register-professional-new` | Register Professional |
| `POST` | `/apis/v1/doctors/resent-verify-email` | Resend Verification Email |
| `POST` | `/apis/v1/doctors/update-professional-new` | Update Professional |
| `POST` | `/apis/v1/doctors/verify-email-otp` | Verify Email OTP |
| `POST` | `/apis/v1/doctors/verify-mobile-otp` | Verify Mobile OTP |
| `GET` | `/apis/v1/masters/affiliated-board` | Get All Affiliated Board |
| `GET` | `/apis/v1/masters/affiliated-board/{id}` | Get Affiliated Board By ID |
| `GET` | `/apis/v1/masters/affiliated-board/states/{id}` | Get Affiliated Board By State ID |
| `GET` | `/apis/v1/masters/colleges/{id}` | Get College By State |
| `GET` | `/apis/v1/masters/colleges/{stateId}/{medicineId}` | Get College By State And Medicine ID |
| `GET` | `/apis/v1/masters/countries` | Get All Countries |
| `GET` | `/apis/v1/masters/countries/{id}` | Get Countries By ID |
| `POST` | `/apis/v1/masters/courses` | List Courses |
| `GET` | `/apis/v1/masters/district` | Get All Districts |
| `GET` | `/apis/v1/masters/district/{id}` | Get Districts By State |
| `GET` | `/apis/v1/masters/languages` | List Government Health Programmes |
| `GET` | `/apis/v1/masters/languages/{id}` | Get Pi Languages By ID |
| `GET` | `/apis/v1/masters/medical-councils` | Get All Medical Council |
| `GET` | `/apis/v1/masters/medical-councils/name` | Get Medical Council By System Of Medicine Name |
| `GET` | `/apis/v1/masters/nurse-councils` | Get All Nurse Councils |
| `GET` | `/apis/v1/masters/states` | Get All States |
| `GET` | `/apis/v1/masters/states/{id}` | Get Status |
| `GET` | `/apis/v1/masters/sub-districts` | Get All Sub Districts |
| `GET` | `/apis/v1/masters/sub-districts/{id}` | Get All Sub Districts 1 |
| `GET` | `/apis/v1/masters/system-of-medicines` | Get All Medical System |
| `GET` | `/apis/v1/masters/universites` | List All University |
| `GET` | `/apis/v1/masters/universites/{id}` | Get University By College |
| `POST` | `/apis/v1/uploads/upload-document` | Upload Documents |
| `POST` | `/FacilityManagement/v1.5/facility/bygeoLocation/searchWithinRadiusWithFilter` | Get Facility Within Radius With Filter |
| `POST` | `/FacilityManagement/v1.5/facility/search` | Search Facility 1 |
| `GET` | `/getPsuDetailsByMinistry` | Get Psu Data |
| `GET` | `/hpid/get/categories` | Fetch HPID Categories |
| `GET` | `/hpid/get/subCategories` | Fetch HPID Sub Categories From Category |
| `POST` | `/password/change/byPassword` | Change Password |
| `POST` | `/password/recover/byAadhaar` | Recover Password Via Aadhaar |
| `POST` | `/password/recover/byMobile/sendMobileOTP` | Generate Mobile OTP 1 |
| `POST` | `/password/recover/byMobile/verifyMobileOTP` | Verify Mobile OTP 1 |
| `POST` | `/password/recover/confirmByAadhaar` | Recover Password Confirm By Aadhaar |
| `POST` | `/password/reset/password` | Reset Password And Session |
| `POST` | `/password/resetPassword` | Reset Password |
| `POST` | `/search/address/filter/deduplicate` | Get Filtered Address Post |
| `POST` | `/v1.0/facility/search-facilities` | Search Facility |
| `POST` | `/v1.5/facility/additional-information` | V15Facility Additional Information |
| `POST` | `/v1.5/facility/basic-information` | V15Basic Facility Information |
| `POST` | `/v1.5/facility/detailed-information` | V15Facility Detailed Information |
| `POST` | `/v1.5/facility/fetch-facility-Sub-type` | Get All Facility Sub Type By Facility Type |
| `POST` | `/v1.5/facility/fetch-facility-type` | Get All Facility Type By Ownership And Sys Of Med |
| `GET` | `/v1.5/facility/get-master-data` | Get Master Data |
| `GET` | `/v1.5/facility/get-master-types` | Get All Master Type |
| `POST` | `/v1.5/facility/get-owner-subtype` | Get All Sub Types By Owner Ship Type And Sub Type |
| `POST` | `/v1.5/facility/get-specialities` | Get All Specialities By System Of Medicine Code |
| `GET` | `/v1.5/facility/lgd/districts` | Get All District By State ID |
| `GET` | `/v1.5/facility/lgd/states` | Get All States By LGD |
| `GET` | `/v1.5/facility/lgd/subdistricts` | Get All Sub District By District Code |
| `POST` | `/v1.5/facility/sendOtpToContact` | Send OTP To Contact |
| `POST` | `/v1.5/facility/submit-facility` | V15Submit Facility Details |
| `POST` | `/v1.5/facility/validateOtp` | Validate OTP |
| `GET` | `/v1/account/getIdCard` | Get Account Png Card |
| `GET` | `/v1/account/information` | Get User Profile By JWT |
| `GET` | `/v1/account/user-details/{hprId}` | Get User Details |
| `POST` | `/v1/bridges/MutipleHRPAddUpdateServices` | Facility Add And Update |
| `POST` | `/v1/forgot/hprId/aadhaar` | Retrieval Health ID By Aadhaar |
| `POST` | `/v1/forgot/hprId/mobile` | Retrieval Health ID By Mobile |
| `POST` | `/v1/forgot/hprId/mobile/generateOtp` | Generate Mobile OTP |
| `POST` | `/v1/registration/aadhaar/checkHpIdAccountExist` | Account Exist |
| `POST` | `/v1/registration/aadhaar/generateMobileOTP` | Generate Mobile OTP |
| `POST` | `/v1/registration/aadhaar/hpid/suggestion` | Get Suggesstion |
| `POST` | `/v1/registration/aadhaar/verifyMobileOTP` | Verify Mobile OTP |
| `GET` | `/v1/search/existsByHprId/{hprId}` | Exists By HPR ID |
| `GET` | `/v1/search/searchByHprId/{hprId}` | Search User By HPR ID |
| `GET` | `/v1/search/searchByMobile/{mobile}` | Search User By Mobile No |
| `POST` | `/v2/registration/aadhaar/createHprIdWithPreVerified` | Create HPR ID V2 |
| `POST` | `/v2/registration/aadhaar/demographicAuthViaMobile` | Demographic Auth Via Mobile |
| `POST` | `/v2/registration/aadhaar/verifyOTP` | Verify OTP |
| `GET` | `/v4/auth/logout` | Logout |
## Headers

| Header | What it is |
| --- | --- |
| `Authorization` |  |
| `REQUEST-ID` | Unique UUID for track the end to end request transaction |
| `TIMESTAMP` | Actual time of the request was initiated, ISO 8601 represents date and time by starting with the year, follow… |
| `X-CM-ID` | Suffix of the consent manager to which the request was intended |
| `x-hprid-auth` | The HPR token of the signed-in professional, from the HPR login. |
| `x-hprid-auth-verifier` | The HPR token of the professional verifying the facility submission. |
| `X-Token` | The HPR token of the signed-in professional, from the HPR login. |
## A request, in full

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

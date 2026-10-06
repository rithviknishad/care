from django.contrib.postgres.fields import ArrayField
from django.db import models

from care.utils.models.base import BaseModel


class AbdmFacility(BaseModel):
    """The HFR facility (HIP) a CARE facility publishes records as."""

    facility = models.OneToOneField(
        "facility.Facility", on_delete=models.CASCADE, related_name="abdm"
    )
    hip_id = models.CharField(max_length=64, unique=True)


class ExchangeDirection(models.TextChoices):
    outbound = "outbound"
    inbound = "inbound"


class ExchangeState(models.TextChoices):
    # outbound
    sent = "sent"
    accepted = "accepted"
    answered = "answered"
    refused = "refused"
    # inbound
    received = "received"
    replied = "replied"
    rejected = "rejected"


class AbdmExchange(BaseModel):
    """
    One request to or from ABDM. An outbound call and the callback that
    answers it are joined by `answered_by` so they read as one exchange.
    """

    request_id = models.CharField(max_length=64, db_index=True)
    direction = models.CharField(max_length=16, choices=ExchangeDirection.choices)
    method = models.CharField(max_length=8, default="POST")
    path = models.CharField(max_length=255)
    hip_id = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(max_length=16, choices=ExchangeState.choices)
    http_status = models.IntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    # Header names mapped to value lengths; values are never stored
    headers = models.JSONField(default=dict)
    body = models.JSONField(null=True, blank=True)
    reply = models.JSONField(null=True, blank=True)
    answered_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="answers",
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    patient = models.ForeignKey(
        "emr.Patient", null=True, blank=True, on_delete=models.SET_NULL
    )
    care_context = models.ForeignKey(
        "abdm.AbdmCareContext",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exchanges",
    )

    class Meta:
        ordering = ["-created_date"]


class AbdmLinkToken(BaseModel):
    patient = models.ForeignKey("emr.Patient", on_delete=models.CASCADE)
    hip_id = models.CharField(max_length=64)
    abha_address = models.CharField(max_length=255)
    token = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "hip_id"], name="unique_abdm_link_token"
            )
        ]


class CareContextStatus(models.TextChoices):
    pending = "pending"
    awaiting_token = "awaiting_token"
    linking = "linking"
    linked = "linked"
    failed = "failed"


class AbdmCareContext(BaseModel):
    """One encounter, published to ABDM as one care context."""

    encounter = models.OneToOneField(
        "emr.Encounter", on_delete=models.CASCADE, related_name="abdm_care_context"
    )
    patient = models.ForeignKey("emr.Patient", on_delete=models.CASCADE)
    hip_id = models.CharField(max_length=64)
    abha_address = models.CharField(max_length=255)
    reference_number = models.CharField(max_length=255, unique=True)
    display = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=CareContextStatus.choices,
        default=CareContextStatus.pending,
    )
    hi_types = ArrayField(models.CharField(max_length=64), default=list)
    linked_hi_types = ArrayField(models.CharField(max_length=64), default=list)
    linked_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_message = models.TextField(blank=True, default="")


class AbdmConsentArtefact(BaseModel):
    consent_id = models.CharField(max_length=64, unique=True)
    hip_id = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    abha_address = models.CharField(max_length=255, blank=True, default="")
    care_contexts = models.JSONField(default=list)
    hi_types = ArrayField(models.CharField(max_length=64), default=list)
    date_from = models.DateTimeField(null=True, blank=True)
    date_to = models.DateTimeField(null=True, blank=True)
    data_erase_at = models.DateTimeField(null=True, blank=True)
    detail = models.JSONField(default=dict)
    signature = models.TextField(blank=True, default="")


class AbdmHealthInformationRequest(BaseModel):
    transaction_id = models.CharField(max_length=64, unique=True)
    consent = models.ForeignKey(
        AbdmConsentArtefact, null=True, blank=True, on_delete=models.SET_NULL
    )
    hip_id = models.CharField(max_length=64)
    data_push_url = models.URLField(max_length=1024)
    date_from = models.DateTimeField(null=True, blank=True)
    date_to = models.DateTimeField(null=True, blank=True)
    key_material = models.JSONField(default=dict)
    session_status = models.CharField(max_length=32, default="ACKNOWLEDGED")
    status_responses = models.JSONField(default=list)
    error_message = models.TextField(blank=True, default="")
    # The bundles as built for this transfer, so the record shows what left
    shared = models.JSONField(default=list)


# CARE as HIU: asking for records other providers hold


class HiuConsentStatus(models.TextChoices):
    # Before ABDM has given the request an id
    sending = "SENDING"
    failed = "FAILED"
    # ABDM's own states
    requested = "REQUESTED"
    granted = "GRANTED"
    denied = "DENIED"
    expired = "EXPIRED"
    revoked = "REVOKED"


class AbdmHiuConsentRequest(BaseModel):
    patient = models.ForeignKey("emr.Patient", on_delete=models.CASCADE)
    facility = models.ForeignKey("facility.Facility", on_delete=models.CASCADE)
    requester = models.ForeignKey(
        "users.User", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    hiu_id = models.CharField(max_length=64)
    abha_address = models.CharField(max_length=255)
    purpose = models.CharField(max_length=16)
    hi_types = ArrayField(models.CharField(max_length=64))
    date_from = models.DateTimeField()
    date_to = models.DateTimeField()
    data_erase_at = models.DateTimeField()
    # REQUEST-ID of the init call, which its callback answers
    request_id = models.CharField(max_length=64, db_index=True)
    consent_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=HiuConsentStatus.choices,
        default=HiuConsentStatus.sending,
    )
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_message = models.TextField(blank=True, default="")


class AbdmHiuConsentArtefact(BaseModel):
    """One per HIP a grant covers; each is fetched and transferred on its own."""

    consent_request = models.ForeignKey(
        AbdmHiuConsentRequest, on_delete=models.CASCADE, related_name="artefacts"
    )
    consent_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, default=HiuConsentStatus.granted)
    hip_id = models.CharField(max_length=64, blank=True, default="")
    hip_name = models.CharField(max_length=255, blank=True, default="")
    care_contexts = models.JSONField(default=list)
    hi_types = ArrayField(models.CharField(max_length=64), default=list)
    date_from = models.DateTimeField(null=True, blank=True)
    date_to = models.DateTimeField(null=True, blank=True)
    data_erase_at = models.DateTimeField(null=True, blank=True)
    detail = models.JSONField(default=dict)
    signature = models.TextField(blank=True, default="")
    # The transfer of this artefact's records
    hi_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    transaction_id = models.CharField(max_length=64, blank=True, db_index=True)
    session_status = models.CharField(max_length=32, blank=True, default="")
    push_token = models.CharField(max_length=64, blank=True, db_index=True)
    # The records land in this database too, so the key adds no exposure; cleared once they arrive
    key_secret = models.JSONField(null=True, blank=True)
    pages_received = models.IntegerField(default=0)
    status_responses = models.JSONField(default=list)
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_message = models.TextField(blank=True, default="")


class AbdmHiuRecord(BaseModel):
    """A decrypted record from another provider; erased with its consent."""

    artefact = models.ForeignKey(
        AbdmHiuConsentArtefact, on_delete=models.CASCADE, related_name="records"
    )
    care_context_reference = models.CharField(max_length=255)
    checksum = models.CharField(max_length=64, blank=True, default="")
    bundle = models.JSONField()


class AbdmProfessional(BaseModel):
    """The HPR ID a CARE user practises under, proven by an HPR login."""

    user = models.OneToOneField(
        "users.User", on_delete=models.CASCADE, related_name="abdm_professional"
    )
    hpr_id = models.CharField(max_length=128, unique=True)
    hpr_id_number = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255, blank=True, default="")
    verified_at = models.DateTimeField()
    linked_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )


class AbdmHfrApplication(BaseModel):
    """A facility's own HFR onboarding: the tracking id HFR issued, until it submits."""

    facility = models.OneToOneField(
        "facility.Facility", on_delete=models.CASCADE, related_name="abdm_hfr"
    )
    tracking_id = models.CharField(max_length=64, blank=True, default="")
    hfr_id = models.CharField(max_length=64, blank=True, default="")
    submitted_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    # What was sent, so a refused submission can be corrected rather than retyped
    information = models.JSONField(default=dict)
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

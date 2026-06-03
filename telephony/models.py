from django.db import models
from django.utils import timezone

import uuid

from .phone_numbers import to_e164

class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.phone})"

    def save(self, *args, **kwargs):
        self.phone = to_e164(self.phone)
        super().save(*args, **kwargs)

class Call(models.Model):
    class Direction(models.TextChoices):
        INCOMING = "incoming", "Incoming"
        OUTGOING = "outgoing", "Outgoing"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call_sid = models.CharField(max_length=255, unique=True)
    stream_sid = models.CharField(max_length=255, blank=True, null=True)
    from_number = models.CharField(max_length=20, blank=True, default="", db_index=True)
    to_number = models.CharField(max_length=20, blank=True, default="", db_index=True)
    direction = models.CharField(
        max_length=20,
        choices=Direction.choices,
        default=Direction.INCOMING,
        db_index=True,
    )
    caller_number = models.CharField(max_length=20, blank=True, default="", db_index=True)
    selected_mode = models.CharField(max_length=100, blank=True, null=True)
    duration = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=100)
    profile = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="calls")
    completed_on = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Call {self.call_sid} - {self.from_number}"

    def mark_completed(self, *, duration: int | None = None) -> None:
        self.status = "completed"
        self.completed_on = timezone.now()
        if duration is not None:
            self.duration = max(0, int(duration))
        self.save(update_fields=["status", "completed_on", "duration", "updated_at"])

    def save(self, *args, **kwargs):
        self.from_number = to_e164(self.from_number)
        self.to_number = to_e164(self.to_number)
        self.caller_number = to_e164(self.caller_number or self.from_number)
        super().save(*args, **kwargs)

class TranscriptTurn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="turns")
    seq_number = models.IntegerField()
    speaker = models.CharField(max_length=50) # 'user' or 'assistant'
    text = models.TextField()
    latency_ms = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Turn {self.seq_number} ({self.speaker}) - Call PK {self.call_id}"

class Summary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="summaries")
    summary_text = models.TextField()
    delivery_status = models.CharField(max_length=100)
    destination = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Summary for {self.call.call_sid}"

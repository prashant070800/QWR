import uuid
from django.db import models

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

class Call(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call_sid = models.CharField(max_length=255, unique=True)
    stream_sid = models.CharField(max_length=255, blank=True, null=True)
    caller_number = models.CharField(max_length=50)
    selected_mode = models.CharField(max_length=100, blank=True, null=True)
    duration = models.IntegerField(default=0)
    status = models.CharField(max_length=100)
    profile = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="calls")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Call {self.call_sid} - {self.caller_number}"

class TranscriptTurn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="turns")
    seq_number = models.IntegerField()
    speaker = models.CharField(max_length=50) # 'user' or 'assistant'
    text = models.TextField()
    latency_ms = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Turn {self.seq_number} ({self.speaker}) - Call {self.call.call_sid}"

class Summary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="summaries")
    summary_text = models.TextField()
    delivery_status = models.CharField(max_length=100)
    destination = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Summary for {self.call.call_sid}"

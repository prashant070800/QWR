from django.contrib import admin
from django.utils.html import format_html
from .models import Profile, Call, TranscriptTurn, Summary

class TranscriptTurnInline(admin.TabularInline):
    model = TranscriptTurn
    extra = 0
    ordering = ('seq_number',)
    readonly_fields = ('seq_number', 'speaker', 'text', 'latency_ms', 'created_at')
    can_delete = False

class SummaryInline(admin.StackedInline):
    model = Summary
    extra = 0
    readonly_fields = ('summary_text', 'delivery_status', 'destination', 'created_at')
    can_delete = False

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('phone', 'name', 'company', 'role', 'city', 'email', 'created_at')
    search_fields = ('phone', 'name', 'company', 'role', 'city', 'email')
    list_filter = ('created_at',)
    ordering = ('-created_at',)

@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ('call_sid', 'caller_number', 'status', 'duration_display', 'selected_mode', 'created_at')
    search_fields = ('call_sid', 'stream_sid', 'caller_number')
    list_filter = ('status', 'selected_mode', 'created_at')
    ordering = ('-created_at',)
    inlines = [TranscriptTurnInline, SummaryInline]
    readonly_fields = ('created_at', 'updated_at')

    def duration_display(self, obj):
        return f"{obj.duration}s"
    duration_display.short_description = "Duration"

@admin.register(TranscriptTurn)
class TranscriptTurnAdmin(admin.ModelAdmin):
    list_display = ('call_link', 'seq_number', 'speaker', 'text_truncated', 'latency_display', 'created_at')
    list_filter = ('speaker', 'created_at')
    search_fields = ('call__call_sid', 'text')
    ordering = ('call', 'seq_number')

    def call_link(self, obj):
        return format_html('<a href="/admin/telephony/call/{}/change/">{}</a>', obj.call.id, obj.call.call_sid)
    call_link.short_description = "Call SID"

    def text_truncated(self, obj):
        if len(obj.text) > 75:
            return f"{obj.text[:75]}..."
        return obj.text
    text_truncated.short_description = "Content"

    def latency_display(self, obj):
        if obj.latency_ms is not None:
            return f"{obj.latency_ms} ms"
        return "-"
    latency_display.short_description = "Latency"

@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = ('call_link', 'summary_truncated', 'delivery_status', 'destination', 'created_at')
    list_filter = ('delivery_status', 'created_at')
    search_fields = ('call__call_sid', 'summary_text', 'destination')
    ordering = ('-created_at',)

    def call_link(self, obj):
        return format_html('<a href="/admin/telephony/call/{}/change/">{}</a>', obj.call.id, obj.call.call_sid)
    call_link.short_description = "Call SID"

    def summary_truncated(self, obj):
        if len(obj.summary_text) > 75:
            return f"{obj.summary_text[:75]}..."
        return obj.summary_text
    summary_truncated.short_description = "Summary"

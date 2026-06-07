from django.views.generic import ListView, DetailView
from django.db.models import Q
from .models import Call, TranscriptTurn, Summary

class DashboardView(ListView):
    model = Call
    template_name = "telephony/dashboard.html"
    context_object_name = "calls"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("profile").order_by("-created_at")
        query = self.request.GET.get("q", "").strip()
        if query:
            # Filter by call SID, phone numbers, or transcript text
            qs = qs.filter(
                Q(call_sid__icontains=query) |
                Q(from_number__icontains=query) |
                Q(to_number__icontains=query) |
                Q(turns__text__icontains=query)
            ).distinct()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        context["active_calls"] = Call.objects.filter(status__iexact="in-progress").count()
        context["total_calls"] = Call.objects.count()
        return context

class CallDetailView(DetailView):
    model = Call
    template_name = "telephony/call_detail.html"
    context_object_name = "call"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        call = self.get_object()
        context["transcripts"] = TranscriptTurn.objects.filter(call=call).order_by("seq_number")
        context["summary"] = Summary.objects.filter(call=call).first()
        return context

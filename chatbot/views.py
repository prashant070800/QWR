from django.shortcuts import render


def chat_view(request):
    """Serve the voice chatbot UI."""
    return render(request, "chatbot/index.html")

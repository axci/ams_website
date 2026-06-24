from django.shortcuts import render

from .models import AboutBlock


def about(request):
    blocks = AboutBlock.objects.filter(is_published=True)
    return render(request, "about/about.html", {"blocks": blocks})

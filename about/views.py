from django.shortcuts import render

from .models import AboutBrandBlock, AboutPage, CompanyDetails


def about(request):
    page = AboutPage.load()
    context = {
        "page": page,
        "specs": page.specs.filter(is_published=True),
        "tags": page.client_tags.filter(is_published=True),
        "brand_blocks": AboutBrandBlock.objects.filter(
            is_published=True
        ).prefetch_related("chips"),
        "centers": list(page.centers.filter(is_published=True)),
        "regions": list(page.regions.filter(is_published=True)),
        "company": CompanyDetails.load(),
    }
    return render(request, "about/about.html", context)
